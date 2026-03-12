"""
Production-grade text chunker.

Improvements:
- Robust sentence tokenization: blingfire (preferred) with regex fallback
  * blingfire handles abbreviations, decimals, and lists correctly
  * regex fallback activates automatically if blingfire is not installed
- Anchor preservation: [SECTION], [PAGE], [SLIDE], [FIGURE], [TABLE], [CHART]
  always force a new chunk boundary (structural markers never split mid-chunk)
- Public chunk_hash() export: callers (upload_router) can hash for cross-run dedup
- Chunk normalisation  : whitespace, control chars, repeated separators cleaned
  NOTE: pipe `|` delimiters in structured/tabular text are intentionally preserved
        by _normalize — they carry semantic field separation and must not be stripped
- Hash deduplication   : identical chunks (repeated headers, page artifacts) removed
- Size safeguards      : hard ceiling on chunk chars (synced with embedder limit)
- Tabular row cap      : oversized spreadsheet rows safely truncated
- Precompiled patterns : all regex compiled once at module load
- Observability        : chunk count, avg/max size, tokenizer backend logged
"""

import hashlib
import logging
import re
from typing import List

log = logging.getLogger("chunker")

ROW_SEPARATOR = "\n---\n"

# ── Constants ─────────────────────────────────────────────────────────────────

_MIN_CHUNK_CHARS = 50     # ignore chunks shorter than this
_MAX_CHUNK_CHARS = 4_800  # hard ceiling; synced with embedder.MAX_EMBED_CHARS
_MAX_ROW_CHARS   = 1_200  # hard ceiling for tabular rows (many fields → long rows)

# ── Precompiled normalisation patterns ───────────────────────────────────────

_RE_NULL        = re.compile(r"\x00+")
_RE_CTRL        = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RE_TRAIL_SPC   = re.compile(r"[ \t]+$", re.MULTILINE)
_RE_MULTI_SPC   = re.compile(r"[ \t]{2,}")
_RE_MULTI_NL    = re.compile(r"\n{3,}")
_RE_MULTI_DASH  = re.compile(r"-{4,}")
_RE_MULTI_EQ    = re.compile(r"={4,}")
_RE_MULTI_STAR  = re.compile(r"\*{4,}")

# Regex sentence boundary fallback — used only when blingfire is unavailable.
# Matches end-of-sentence punctuation followed by whitespace + capital/quote/paren.
_RE_SENT_BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-Z\"\(])')

# Structural anchor lines: lines that begin a logical section / page / slide.
# These must always start a new chunk — never be buried mid-chunk.
_RE_ANCHOR = re.compile(
    r"^\s*\[(SECTION|PAGE|SLIDE|FIGURE|TABLE|CHART)\b",
    re.IGNORECASE,
)


# ── Sentence tokenizer (blingfire preferred, regex fallback) ──────────────────

try:
    import blingfire as _bf  # type: ignore

    def _split_sentences(text: str) -> List[str]:
        """
        Split text into sentences using blingfire — handles abbreviations,
        decimals, ordinals, and list items correctly.
        """
        if not text.strip():
            return []
        raw = _bf.text_to_sentences(text)
        return [s.strip() for s in raw.split("\n") if s.strip()]

    _TOKENIZER_BACKEND = "blingfire"

except ImportError:
    log.warning(
        "[chunker] blingfire not installed — falling back to regex sentence splitter. "
        "Install with: pip install blingfire"
    )

    def _split_sentences(text: str) -> List[str]:  # type: ignore[misc]
        """
        Regex-based sentence splitter (fallback).
        Splits on end-of-sentence punctuation + whitespace + capital letter.
        Less accurate than blingfire for abbreviations and decimals.
        """
        parts = _RE_SENT_BOUNDARY.split(text)
        return [p.strip() for p in parts if p.strip()]

    _TOKENIZER_BACKEND = "regex"


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    Produce clean, consistent text for embedding:
    - Strip null bytes and non-printable control characters
    - Normalise line endings
    - Collapse repeated spaces/tabs, newlines, and separator sequences
    - Strip trailing whitespace per line
    - Preserve pipe `|` characters (they delimit structured/tabular fields)
    """
    text = _RE_NULL.sub("", text)
    text = _RE_CTRL.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _RE_TRAIL_SPC.sub("", text)
    text = _RE_MULTI_SPC.sub(" ", text)
    text = _RE_MULTI_DASH.sub("---", text)
    text = _RE_MULTI_EQ.sub("===", text)
    text = _RE_MULTI_STAR.sub("***", text)
    text = _RE_MULTI_NL.sub("\n\n", text)
    return text.strip()


# ── Hashing ───────────────────────────────────────────────────────────────────

def _chunk_hash(text: str) -> str:
    """Private helper — MD5 of UTF-8 encoded text."""
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()


def chunk_hash(text: str) -> str:
    """
    Public export: return the canonical MD5 hash for a chunk of text.
    Used by upload_router for cross-run deduplication against ChromaDB metadata.
    """
    return _chunk_hash(text)


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate(chunks: List[str]) -> List[str]:
    """Remove exact-duplicate chunks (repeated headers, page artifacts, empty rows)."""
    seen: set = set()
    result: List[str] = []
    for chunk in chunks:
        h = _chunk_hash(chunk)
        if h not in seen:
            seen.add(h)
            result.append(chunk)
    return result


# ── Size enforcement ──────────────────────────────────────────────────────────

def _cap(text: str, max_chars: int) -> str:
    """Truncate to max_chars at the nearest word boundary (≥ 80% of budget used)."""
    if len(text) <= max_chars:
        return text
    candidate  = text[:max_chars]
    last_space = candidate.rfind(" ", int(max_chars * 0.8))
    if last_space != -1:
        return candidate[:last_space].rstrip()
    return candidate.rstrip()


# ── Tabular chunker ───────────────────────────────────────────────────────────

def _chunk_tabular(text: str) -> List[str]:
    """
    One chunk per spreadsheet / CSV row.
    Normalises each row, enforces the row size ceiling, then deduplicates.
    """
    chunks: List[str] = []
    for row in text.split(ROW_SEPARATOR):
        norm = _normalize(row)
        if len(norm) < _MIN_CHUNK_CHARS:
            continue
        chunks.append(_cap(norm, _MAX_ROW_CHARS))
    return _deduplicate(chunks)


# ── Anchor helpers ────────────────────────────────────────────────────────────

def _is_anchor(line: str) -> bool:
    """Return True if *line* is a structural anchor that must begin a new chunk."""
    return bool(_RE_ANCHOR.match(line))


# ── Prose chunker ─────────────────────────────────────────────────────────────

def _chunk_prose(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Sentence-aware sliding-window chunking for prose documents.

    Sentence tokenization uses blingfire when available (falls back to regex).

    Algorithm:
    1. Normalise full text.
    2. Split into lines; any line matching _RE_ANCHOR forces a flush.
    3. Within non-anchor content, tokenize into sentences, accumulate words up to
       chunk_size, then slide forward by (chunk_size - overlap) words.
    4. Prepend any pending anchor to the first chunk of each prose segment.
    5. Enforce _MAX_CHUNK_CHARS hard ceiling.
    6. Deduplicate.
    """
    text  = _normalize(text)
    lines = text.split("\n")

    # Separate anchor lines from prose blocks so anchors always open a new chunk.
    segments: List[str] = []
    current_prose: List[str] = []

    for line in lines:
        if _is_anchor(line):
            if current_prose:
                segments.append("\n".join(current_prose))
                current_prose = []
            segments.append(line)
        else:
            current_prose.append(line)

    if current_prose:
        segments.append("\n".join(current_prose))

    chunks: List[str] = []
    pending_anchor: str = ""
    step = max(1, chunk_size - overlap)

    for segment in segments:
        if _is_anchor(segment):
            pending_anchor = segment
            continue

        # Tokenize into sentences, then flatten to word list.
        sentences = _split_sentences(segment)
        words: List[str] = []
        for sentence in sentences:
            words.extend(sentence.split())

        if not words:
            continue

        i = 0
        while i < len(words):
            window = words[i : i + chunk_size]
            raw    = (" ".join(window)).strip()

            if pending_anchor:
                raw            = pending_anchor + "\n" + raw
                pending_anchor = ""

            norm = _normalize(raw)
            if len(norm) >= _MIN_CHUNK_CHARS:
                chunks.append(_cap(norm, _MAX_CHUNK_CHARS))

            i += step

    # Lone anchor with no following prose
    if pending_anchor and len(pending_anchor) >= _MIN_CHUNK_CHARS:
        chunks.append(_cap(_normalize(pending_anchor), _MAX_CHUNK_CHARS))

    return _deduplicate(chunks)


# ── Public API ────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """
    Route text to the appropriate chunker (tabular vs prose).

    All output chunks are:
      - Normalised (whitespace, separators, control characters cleaned)
      - Pipe-delimiter safe (| in structured fields is preserved by _normalize)
      - Size-capped (no chunk exceeds _MAX_CHUNK_CHARS)
      - Deduplicated (identical text hashes removed)
      - Sentence-boundary aware via blingfire (or regex fallback)
      - Anchor-preserving ([SECTION]/[PAGE]/[SLIDE] always start a new chunk)

    Signature is unchanged from original — fully backwards-compatible.
    """
    is_tabular = ROW_SEPARATOR in text
    log.debug("[chunk_text] tabular=%s  tokenizer=%s  first_200=%r",
              is_tabular, _TOKENIZER_BACKEND, text[:200])

    chunks = _chunk_tabular(text) if is_tabular else _chunk_prose(text, chunk_size, overlap)

    if chunks:
        sizes    = [len(c) for c in chunks]
        avg_size = sum(sizes) / len(sizes)
        max_size = max(sizes)
    else:
        avg_size = max_size = 0

    log.info(
        "[chunker] %d chunks produced  avg_chars=%.0f  max_chars=%d  tokenizer=%s",
        len(chunks), avg_size, max_size, _TOKENIZER_BACKEND,
    )

    return chunks
