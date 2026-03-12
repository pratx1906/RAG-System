"""
Production-grade embedder.

Improvements:
- Persistent SQLite embedding cache (L2) behind in-memory LRU cache (L1)
  * Survives service restarts — embeddings never recomputed for seen chunks
  * Cache key: MD5 hash of the (truncated) chunk text
  * Cache value: JSON-serialised embedding vector stored in embed_cache.db
  * Path configurable via EMBED_CACHE_DB env var
- Per-request embedding latency metrics
  * embedding_latency_ms logged at DEBUG per chunk
  * p50 and p95 latency reported at INFO level per batch for anomaly detection
- Dynamic concurrency: min(8, EMBED_CONCURRENCY env) defaulting to cpu_count
- Wave-based batching: EMBED_BATCH_SIZE chunks per wave to bound memory
- Embedding failure safeguard: abort if success rate < MIN_SUCCESS_RATE
- Retry logic per chunk (up to 3 attempts, linear back-off)
- No zero-vector fallback — failed chunks return None; callers must filter
- Token-aware truncation at sentence/word boundaries
- Throughput metrics: chunks/sec logged per batch
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import ollama

from backend.config import OLLAMA_EMBED_MODEL

log = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────

# nomic-embed-text hard limit: 8192 tokens.
# ~4 chars/token → 8192 * 4 = 32 768 chars theoretical max.
# We stay conservative at 5 000 chars to leave headroom for sub-word tokens.
MAX_EMBED_CHARS = 5_000

_MAX_RETRIES     = 3      # attempts before declaring a chunk failed
_RETRY_BASE_SECS = 0.5   # delay = _RETRY_BASE_SECS * attempt number

# Dynamic concurrency: honour EMBED_CONCURRENCY env var, else derive from cpu_count
_CONCURRENCY: int = min(
    8,
    int(os.getenv("EMBED_CONCURRENCY", str(min(8, os.cpu_count() or 4))))
)

# Wave size: how many chunks to submit to the thread pool at once
_BATCH_SIZE: int = int(os.getenv("EMBED_BATCH_SIZE", "10"))

# Minimum fraction of chunks that must embed successfully before aborting
MIN_SUCCESS_RATE: float = float(os.getenv("EMBED_MIN_SUCCESS_RATE", "0.70"))

# ── Persistent SQLite cache (L2) ──────────────────────────────────────────────

# Default path: <project_root>/data/embed_cache.db  (auto-created)
_EMBED_CACHE_DB: str = os.getenv(
    "EMBED_CACHE_DB",
    os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "embed_cache.db")
    ),
)

_disk_lock = threading.Lock()
_disk_con: Optional[sqlite3.Connection] = None


def _get_disk_con() -> sqlite3.Connection:
    """Return (and lazily create) the shared SQLite connection."""
    global _disk_con
    if _disk_con is not None:
        return _disk_con
    with _disk_lock:
        if _disk_con is not None:   # double-checked under lock
            return _disk_con
        os.makedirs(os.path.dirname(_EMBED_CACHE_DB), exist_ok=True)
        con = sqlite3.connect(_EMBED_CACHE_DB, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
        con.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                hash     TEXT PRIMARY KEY,
                vector   TEXT NOT NULL,
                created  REAL NOT NULL
            )
        """)
        con.commit()
        _disk_con = con
        log.info("[embedder] SQLite cache initialised at %s", _EMBED_CACHE_DB)
    return _disk_con


def _disk_get(key: str) -> Optional[List[float]]:
    try:
        con = _get_disk_con()
        with _disk_lock:
            row = con.execute(
                "SELECT vector FROM embeddings WHERE hash = ?", (key,)
            ).fetchone()
        if row:
            return json.loads(row[0])
    except Exception as exc:
        log.warning("[embedder] disk cache read error: %s", exc)
    return None


def _disk_set(key: str, emb: List[float]) -> None:
    try:
        con = _get_disk_con()
        with _disk_lock:
            con.execute(
                "INSERT OR REPLACE INTO embeddings (hash, vector, created) VALUES (?,?,?)",
                (key, json.dumps(emb), time.time()),
            )
            con.commit()
    except Exception as exc:
        log.warning("[embedder] disk cache write error: %s", exc)


# ── In-memory LRU cache (L1, in front of SQLite) ─────────────────────────────

_L1_MAX   = 1_000
_l1_cache: Dict[str, List[float]] = {}
_l1_lock  = threading.Lock()


def _l1_get(key: str) -> Optional[List[float]]:
    with _l1_lock:
        return _l1_cache.get(key)


def _l1_set(key: str, emb: List[float]) -> None:
    with _l1_lock:
        if len(_l1_cache) >= _L1_MAX:
            oldest = next(iter(_l1_cache))
            del _l1_cache[oldest]
        _l1_cache[key] = emb


def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()


def _cache_get(key: str) -> Optional[List[float]]:
    """Two-level lookup: L1 (memory) → L2 (SQLite)."""
    emb = _l1_get(key)
    if emb is not None:
        return emb
    emb = _disk_get(key)
    if emb is not None:
        _l1_set(key, emb)   # promote to L1
    return emb


def _cache_set(key: str, emb: List[float]) -> None:
    """Write to both L1 and L2."""
    _l1_set(key, emb)
    _disk_set(key, emb)


# ── Truncation ────────────────────────────────────────────────────────────────

def _truncate_safe(text: str, max_chars: int = MAX_EMBED_CHARS) -> str:
    """
    Truncate text to ≤ max_chars while preserving semantic structure.
    Priority order: sentence boundary → paragraph boundary → word boundary → hard cut.
    Uses at least 75% of the budget before accepting a boundary.
    """
    if len(text) <= max_chars:
        return text

    candidate = text[:max_chars]
    floor = int(max_chars * 0.75)

    for delim in (".\n", ". ", "!\n", "! ", "?\n", "? ", "\n\n"):
        idx = candidate.rfind(delim, floor)
        if idx != -1:
            return candidate[: idx + 1].rstrip()

    last_space = candidate.rfind(" ", floor)
    if last_space != -1:
        return candidate[:last_space].rstrip()

    return candidate.rstrip()


# ── Per-chunk embedding with retry ───────────────────────────────────────────

def _embed_one(args: Tuple[int, str]) -> Tuple[int, Optional[List[float]], float]:
    """
    Embed a single text chunk with up to _MAX_RETRIES attempts.
    Checks L1+L2 cache first; on a miss, calls Ollama and writes both caches.

    Returns (original_index, embedding_or_None, embedding_latency_ms).
    latency_ms is 0.0 on a cache hit (no network call made).
    """
    idx, text  = args
    safe_text  = _truncate_safe(text)
    key        = _cache_key(safe_text)

    cached = _cache_get(key)
    if cached is not None:
        log.debug("[embedder] idx=%d  cache_hit=L1/L2", idx)
        return idx, cached, 0.0

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            t0           = time.monotonic()
            resp         = ollama.embeddings(model=OLLAMA_EMBED_MODEL, prompt=safe_text)
            emb          = resp["embedding"]
            latency_ms   = (time.monotonic() - t0) * 1_000

            log.debug(
                "[embedder] idx=%d  chars=%d  attempt=%d  embedding_latency_ms=%.1f",
                idx, len(safe_text), attempt, latency_ms,
            )
            _cache_set(key, emb)
            return idx, emb, latency_ms

        except Exception as exc:
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BASE_SECS * attempt
                log.warning(
                    "[embedder] chunk=%d attempt=%d/%d failed (%s) – retrying in %.1fs",
                    idx, attempt, _MAX_RETRIES, exc, wait,
                )
                time.sleep(wait)
            else:
                log.error(
                    "[embedder] chunk=%d PERMANENT FAILURE after %d attempts: %s",
                    idx, _MAX_RETRIES, exc,
                )

    return idx, None, 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def embed_texts(texts: List[str]) -> List[Optional[List[float]]]:
    """
    Embed a list of texts using wave-batched concurrent Ollama requests.

    Processing is split into waves of _BATCH_SIZE to bound memory usage.
    Returns a list **aligned with** `texts`:
      - List[float]  → successful embedding
      - None         → permanent failure after retries (NO zero-vector inserted)

    Callers must filter out None entries before persisting to the vector store.
    Raises RuntimeError if the overall success rate falls below MIN_SUCCESS_RATE.
    """
    if not texts:
        return []

    n                = len(texts)
    results: List[Optional[List[float]]] = [None] * n
    latencies_ms: List[float] = []   # only Ollama calls (cache hits excluded)
    t_start          = time.monotonic()

    # Process in waves to bound peak memory
    for wave_start in range(0, n, _BATCH_SIZE):
        global_wave = [
            (wave_start + i, text)
            for i, text in enumerate(texts[wave_start : wave_start + _BATCH_SIZE])
        ]

        with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
            futures = {pool.submit(_embed_one, item): item[0] for item in global_wave}
            for fut in as_completed(futures):
                try:
                    idx, emb, lat_ms = fut.result()
                    results[idx] = emb
                    if emb is not None and lat_ms > 0.0:
                        latencies_ms.append(lat_ms)
                except Exception as exc:
                    i = futures[fut]
                    log.error("[embedder] unexpected future error for chunk %d: %s", i, exc)

    total    = time.monotonic() - t_start
    success  = sum(1 for e in results if e is not None)
    fail     = n - success
    cache_hits = success - len(latencies_ms)

    avg_chars  = sum(len(t) for t in texts) / n if n else 0
    max_chars  = max((len(t) for t in texts), default=0)
    throughput = success / total if total > 0 else 0.0

    # Latency percentiles (Ollama calls only — cache hits are ~0 ms)
    if latencies_ms:
        s    = sorted(latencies_ms)
        p50  = s[len(s) // 2]
        p95  = s[min(int(len(s) * 0.95), len(s) - 1)]
        avg_lat = sum(s) / len(s)
    else:
        p50 = p95 = avg_lat = 0.0

    log.info(
        "[embedder] %d/%d embedded in %.2fs  throughput=%.1f chunks/s  "
        "cache_hits=%d  ollama_calls=%d  "
        "embedding_latency_ms avg=%.1f p50=%.1f p95=%.1f  "
        "avg_chunk_chars=%.0f  max_chunk_chars=%d  failures=%d",
        success, n, total, throughput,
        cache_hits, len(latencies_ms),
        avg_lat, p50, p95,
        avg_chars, max_chars, fail,
    )

    # Abort if too many chunks failed
    success_rate = success / n if n else 1.0
    if success_rate < MIN_SUCCESS_RATE:
        raise RuntimeError(
            f"Embedding success rate {success_rate:.1%} is below the minimum "
            f"threshold of {MIN_SUCCESS_RATE:.1%} ({fail}/{n} chunks failed). "
            "Aborting to avoid storing a severely incomplete document."
        )

    return results
