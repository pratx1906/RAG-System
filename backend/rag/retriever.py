"""
Production-grade RAG retriever for Constelli.

Pipeline:
  Query → Expansion → Parallel(Vector + BM25) → RRF Fusion
        → Dedup → Cross-Encoder Rerank → Smart Scoring
        → Document-First Selection → MMR → Token Budget
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.db.chroma_client import get_documents_collection
from backend.ingestion.embedder import embed_texts

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Optional dependencies (graceful degradation if missing)
# ──────────────────────────────────────────────────────────────────────────────

try:
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except ImportError:
    _HAS_BM25 = False
    log.warning("[Retriever] rank_bm25 not installed – BM25 disabled. pip install rank-bm25")

try:
    from sentence_transformers import CrossEncoder
    _HAS_CROSS_ENCODER = True
except ImportError:
    _HAS_CROSS_ENCODER = False
    log.warning("[Retriever] sentence-transformers not available – reranking disabled")

# ──────────────────────────────────────────────────────────────────────────────
# Tuning constants
# ──────────────────────────────────────────────────────────────────────────────

_RERANKER_MODEL          = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_RERANKER_FALLBACK       = "BAAI/bge-reranker-large"

_RRF_K                   = 60     # reciprocal rank fusion constant
_MAX_CANDIDATES          = 40     # candidates fed into cross-encoder
_MAX_CHUNKS_PER_DOC      = 2      # chunk diversity cap per filename
_MMR_LAMBDA              = 0.7    # relevance vs. diversity trade-off
_TOKEN_BUDGET            = 6000   # approx context window in tokens
_CHARS_PER_TOKEN         = 4      # rough chars-to-tokens conversion

# Final score weights (must sum to 1.0)
_W_RERANKER              = 0.7
_W_VECTOR                = 0.2
_W_RECENCY               = 0.1

_SEMANTIC_CACHE_SIM      = 0.95   # cosine threshold for cache hit
_SEMANTIC_CACHE_MAX      = 128    # max cached queries

_BM25_TTL_SECS           = 300    # rebuild BM25 index if stale (5 min)

# ──────────────────────────────────────────────────────────────────────────────
# Singleton ChromaDB collection
# ──────────────────────────────────────────────────────────────────────────────

_collection       = None
_collection_lock  = threading.Lock()


def _get_collection():
    global _collection
    if _collection is None:
        with _collection_lock:
            if _collection is None:
                _collection = get_documents_collection()
    return _collection


# ──────────────────────────────────────────────────────────────────────────────
# BM25 index  (lazy build, TTL-based refresh)
# ──────────────────────────────────────────────────────────────────────────────

_bm25_obj:       Optional[object] = None
_bm25_corpus:    List[Dict]       = []
_bm25_count:     int              = -1
_bm25_built_at:  float            = 0.0
_bm25_lock       = threading.Lock()


def _get_bm25() -> Tuple[Optional[object], List[Dict]]:
    """Return (BM25Okapi, corpus). Rebuilds when collection grows or TTL expires."""
    global _bm25_obj, _bm25_corpus, _bm25_count, _bm25_built_at

    if not _HAS_BM25:
        return None, []

    col           = _get_collection()
    current_count = col.count()
    age           = time.monotonic() - _bm25_built_at
    stale         = age > _BM25_TTL_SECS or current_count != _bm25_count

    if not stale and _bm25_obj is not None:
        return _bm25_obj, _bm25_corpus

    with _bm25_lock:
        # re-check under lock
        age   = time.monotonic() - _bm25_built_at
        stale = age > _BM25_TTL_SECS or current_count != _bm25_count
        if not stale and _bm25_obj is not None:
            return _bm25_obj, _bm25_corpus

        if current_count == 0:
            _bm25_obj, _bm25_corpus, _bm25_count = None, [], 0
            _bm25_built_at = time.monotonic()
            return None, []

        try:
            res       = col.get(include=["documents", "metadatas"], limit=current_count)
            corpus    = [_meta_to_chunk(d, m) for d, m in zip(res["documents"], res["metadatas"])]
            tokenized = [d.lower().split() for d in res["documents"]]
            _bm25_obj      = BM25Okapi(tokenized)  # type: ignore[call-arg]
            _bm25_corpus   = corpus
            _bm25_count    = current_count
            _bm25_built_at = time.monotonic()
            log.debug(f"[BM25] index built with {current_count} docs")
        except Exception as exc:
            log.warning(f"[BM25] index build failed: {exc}")
            _bm25_obj, _bm25_corpus = None, []

    return _bm25_obj, _bm25_corpus


# ──────────────────────────────────────────────────────────────────────────────
# Cross-encoder  (lazy singleton, tries large model then lightweight fallback)
# ──────────────────────────────────────────────────────────────────────────────

_reranker         = None
_reranker_lock    = threading.Lock()
_reranker_failed  = False


def _get_reranker():
    global _reranker, _reranker_failed
    if not _HAS_CROSS_ENCODER or _reranker_failed:
        return None
    if _reranker is not None:
        return _reranker
    with _reranker_lock:
        if _reranker is not None:
            return _reranker
        for model in (_RERANKER_MODEL, _RERANKER_FALLBACK):
            try:
                _reranker = CrossEncoder(model)  # type: ignore[call-arg]
                log.info(f"[Reranker] loaded: {model}")
                return _reranker
            except Exception as exc:
                log.warning(f"[Reranker] {model} unavailable: {exc}")
        _reranker_failed = True
        log.warning("[Reranker] all models failed – falling back to vector score")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Embedding cache  (lru_cache per text  +  semantic query cache)
# ──────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=512)
def _cached_embed(text: str) -> Tuple[float, ...]:
    """Cache a single text's embedding as a hashable tuple."""
    return tuple(embed_texts([text])[0])


def _embed_batch(texts: List[str]) -> List[np.ndarray]:
    """Embed a list of texts, reusing lru_cache hits."""
    return [np.array(_cached_embed(t)) for t in texts]


# Semantic query cache: list of (query_vec, results)
_sem_cache:      List[Tuple[np.ndarray, List[Dict]]] = []
_sem_cache_lock  = threading.Lock()


def _cache_lookup(qvec: np.ndarray) -> Optional[List[Dict]]:
    with _sem_cache_lock:
        if not _sem_cache:
            return None
        q = qvec / (np.linalg.norm(qvec) or 1.0)
        for cvec, results in _sem_cache:
            c   = cvec / (np.linalg.norm(cvec) or 1.0)
            sim = float(np.dot(q, c))
            if sim >= _SEMANTIC_CACHE_SIM:
                log.debug(f"[SemanticCache] hit  sim={sim:.3f}")
                return results
    return None


def _cache_store(qvec: np.ndarray, results: List[Dict]) -> None:
    with _sem_cache_lock:
        _sem_cache.append((qvec.copy(), results))
        if len(_sem_cache) > _SEMANTIC_CACHE_MAX:
            _sem_cache.pop(0)


# ──────────────────────────────────────────────────────────────────────────────
# Query expansion  (rule-based: synonyms, paraphrases, entity variations)
# ──────────────────────────────────────────────────────────────────────────────

_SYNONYMS: Dict[str, str] = {
    "performance": "efficiency",    "cost":        "budget",
    "risk":        "concern",       "requirement": "specification",
    "design":      "architecture",  "analysis":    "assessment",
    "meeting":     "discussion",    "issue":       "problem",
    "feature":     "functionality", "deadline":    "timeline",
    "update":      "revision",      "status":      "progress",
    "plan":        "roadmap",       "data":        "information",
    "result":      "outcome",       "report":      "summary",
    "team":        "group",         "project":     "initiative",
}

_STOPWORDS = frozenset({
    "the","a","an","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","could",
    "should","may","might","can","about","for","in","on","at",
    "to","of","and","or","but","not","what","how","why","when",
    "where","who","which","that","this","these","those","it","its",
    "me","my","we","our","you","your","he","she","they","their",
})

_WH_RE = re.compile(
    r'^(?:what\s+(?:is|are|was|were)|how\s+(?:to|does|do|did|is|are)|'
    r'why\s+(?:is|are|was|did|do))\s+',
    re.IGNORECASE,
)


def _expand_queries(query: str) -> List[str]:
    """Generate up to 5 rule-based query variants for improved recall."""
    variants: List[str] = [query]
    q_low = query.lower().strip()

    # Variant 2: document-search framing
    variants.append(f"document section about: {query}")

    # Variant 3: wh-question → declarative
    m = _WH_RE.match(q_low)
    if m:
        variants.append(f"information about {query[m.end():]}")
    else:
        variants.append(f"find relevant details: {query}")

    # Variant 4: synonym substitution
    for word, syn in _SYNONYMS.items():
        if re.search(r'\b' + re.escape(word) + r'\b', q_low):
            subst = re.sub(r'\b' + re.escape(word) + r'\b', syn, query, flags=re.IGNORECASE)
            if subst.lower() != q_low:
                variants.append(subst)
            break

    # Variant 5: keyword-only (strip stopwords and short tokens)
    keywords = [w for w in re.findall(r'\b\w{3,}\b', query) if w.lower() not in _STOPWORDS]
    kw_str   = " ".join(keywords)
    if kw_str and kw_str.lower() != q_low:
        variants.append(kw_str)

    # Deduplicate, preserve order, cap at 5
    seen: set = set()
    unique: List[str] = []
    for v in variants:
        k = v.lower().strip()
        if k not in seen and k:
            seen.add(k)
            unique.append(v)

    return unique[:5]


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()


def _normalize_distance(dist: float) -> float:
    return 1.0 / (1.0 + dist)


def _recency_score(uploaded_at: str) -> float:
    """1.0 = just uploaded; decays with ~30-day half-life. 0.5 = unknown."""
    if not uploaded_at:
        return 0.5
    try:
        s  = str(uploaded_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = max(0, (datetime.now(tz=timezone.utc) - dt).days)
        return 1.0 / (1.0 + days / 30.0)
    except Exception:
        return 0.5


def _meta_to_chunk(doc: str, meta: dict, vector_score: float = 1.0) -> Dict:
    """Convert a raw Chroma (document, metadata) pair into a working chunk dict."""
    return {
        "text":          doc,
        "user":          meta.get("user_name",     "Unknown"),
        "email":         meta.get("user_email",    ""),
        "user_id":       meta.get("user_id",       ""),
        "filename":      meta.get("filename",      ""),
        "document_type": meta.get("document_type", ""),
        "doc_category":  meta.get("doc_category",  ""),
        "uploaded_at":   meta.get("uploaded_at",   ""),
        "total_chunks":  meta.get("total_chunks",  0),
        "relevance_score": round(vector_score, 4),
        "_vector_score": vector_score,
        "_hash":         _text_hash(doc),
    }


def _public_chunk(chunk: Dict) -> Dict:
    """Strip internal `_*` fields; expose `_final_score` as `relevance_score`."""
    return {
        "text":          chunk["text"],
        "user":          chunk.get("user",          "Unknown"),
        "email":         chunk.get("email",         ""),
        "user_id":       chunk.get("user_id",       ""),
        "filename":      chunk.get("filename",      ""),
        "document_type": chunk.get("document_type", ""),
        "doc_category":  chunk.get("doc_category",  ""),
        "uploaded_at":   chunk.get("uploaded_at",   ""),
        "total_chunks":  chunk.get("total_chunks",  0),
        "relevance_score": round(
            chunk.get("_final_score", chunk.get("relevance_score", 0.0)), 4
        ),
    }


def _build_where(filter_user: Optional[str], filters: Optional[Dict]) -> Optional[Dict]:
    conditions = []
    if filter_user:
        conditions.append({"user_email": filter_user})
    if filters:
        for k, v in filters.items():
            conditions.append({k: v})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


# ──────────────────────────────────────────────────────────────────────────────
# Vector search
# ──────────────────────────────────────────────────────────────────────────────

def _vector_search(
    query_emb:    np.ndarray,
    n_results:    int            = _MAX_CANDIDATES,
    where_filter: Optional[Dict] = None,
) -> List[Dict]:
    col   = _get_collection()
    count = col.count()
    if count == 0:
        return []
    try:
        res = col.query(
            query_embeddings=[query_emb.tolist()],
            n_results=min(n_results, count),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        log.warning(f"[VectorSearch] failed: {exc}")
        return []

    return [
        _meta_to_chunk(doc, meta, _normalize_distance(dist))
        for doc, meta, dist in zip(
            res["documents"][0],
            res["metadatas"][0],
            res["distances"][0],
        )
    ]


# ──────────────────────────────────────────────────────────────────────────────
# BM25 search
# ──────────────────────────────────────────────────────────────────────────────

def _bm25_search(query: str, n_results: int = _MAX_CANDIDATES) -> List[Dict]:
    bm25, corpus = _get_bm25()
    if bm25 is None or not corpus:
        return []

    scores  = bm25.get_scores(query.lower().split())  # type: ignore[attr-defined]
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:n_results]

    results = []
    for idx, score in indexed:
        if score <= 0:
            continue
        chunk = dict(corpus[idx])
        chunk["_bm25_score"] = float(score)
        chunk["_hash"]       = _text_hash(chunk["text"])
        results.append(chunk)
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Reciprocal Rank Fusion
# ──────────────────────────────────────────────────────────────────────────────

def _rrf_merge(ranked_lists: List[List[Dict]], k: int = _RRF_K) -> List[Dict]:
    """Merge ranked lists via RRF; keep best _vector_score per unique chunk."""
    rrf:     Dict[str, float] = defaultdict(float)
    by_hash: Dict[str, Dict]  = {}

    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked):
            h = chunk.get("_hash") or _text_hash(chunk["text"])
            rrf[h] += 1.0 / (k + rank + 1)
            if h not in by_hash:
                by_hash[h] = chunk
            else:
                # keep the highest vector score seen across all lists
                if chunk.get("_vector_score", 0) > by_hash[h].get("_vector_score", 0):
                    by_hash[h]["_vector_score"] = chunk["_vector_score"]

    merged = sorted(by_hash.values(), key=lambda c: rrf[c["_hash"]], reverse=True)
    for c in merged:
        c["_rrf_score"] = rrf[c["_hash"]]
    return merged


# ──────────────────────────────────────────────────────────────────────────────
# Cross-encoder reranking
# ──────────────────────────────────────────────────────────────────────────────

def _rerank(query: str, candidates: List[Dict]) -> List[Dict]:
    """Add `_reranker_score` to each candidate. Falls back to vector score."""
    reranker = _get_reranker()
    if reranker is None:
        for c in candidates:
            c["_reranker_score"] = c.get("_vector_score", c.get("relevance_score", 0.5))
        return candidates

    pairs = [(query, c["text"][:512]) for c in candidates]
    try:
        raw = reranker.predict(pairs)  # type: ignore[attr-defined]
        for chunk, logit in zip(candidates, raw):
            # bge-reranker-large returns logits → sigmoid normalises to [0, 1]
            chunk["_reranker_score"] = float(1.0 / (1.0 + np.exp(-float(logit))))
    except Exception as exc:
        log.warning(f"[Reranker] predict failed: {exc}")
        for c in candidates:
            c["_reranker_score"] = c.get("_vector_score", c.get("relevance_score", 0.5))

    return sorted(candidates, key=lambda c: c["_reranker_score"], reverse=True)


# ──────────────────────────────────────────────────────────────────────────────
# Smart scoring
# ──────────────────────────────────────────────────────────────────────────────

def _compute_final_score(chunk: Dict) -> float:
    """
    final_score = 0.7 * reranker_score
               + 0.2 * vector_similarity
               + 0.1 * recency_score
    """
    reranker = chunk.get("_reranker_score", 0.5)
    vector   = chunk.get("_vector_score",   chunk.get("relevance_score", 0.5))
    recency  = _recency_score(chunk.get("uploaded_at", ""))
    return round(_W_RERANKER * reranker + _W_VECTOR * vector + _W_RECENCY * recency, 4)


# ──────────────────────────────────────────────────────────────────────────────
# Document-first selection
# ──────────────────────────────────────────────────────────────────────────────

def _document_first(
    chunks:      List[Dict],
    top_docs:    int = 10,
    max_per_doc: int = _MAX_CHUNKS_PER_DOC,
) -> List[Dict]:
    """
    Aggregate chunk scores by filename → rank documents →
    return best `max_per_doc` chunks per top document.
    """
    doc_score:  Dict[str, float]      = defaultdict(float)
    doc_chunks: Dict[str, List[Dict]] = defaultdict(list)

    for c in chunks:
        fn = c.get("filename", "")
        doc_score[fn]  += c.get("_final_score", 0.0)
        doc_chunks[fn].append(c)

    top = sorted(doc_score, key=lambda f: doc_score[f], reverse=True)[:top_docs]
    selected: List[Dict] = []
    for fn in top:
        best = sorted(doc_chunks[fn], key=lambda c: c.get("_final_score", 0.0), reverse=True)
        selected.extend(best[:max_per_doc])

    return sorted(selected, key=lambda c: c.get("_final_score", 0.0), reverse=True)


# ──────────────────────────────────────────────────────────────────────────────
# Maximal Marginal Relevance
# ──────────────────────────────────────────────────────────────────────────────

def _mmr(
    candidates: List[Dict],
    query_emb:  np.ndarray,
    lambda_:    float = _MMR_LAMBDA,
    top_k:      int   = 10,
) -> List[Dict]:
    """Select `top_k` diverse chunks using MMR (λ=0.7 favours relevance)."""
    if len(candidates) <= top_k:
        return candidates

    # Embed candidates (lru_cache makes repeat texts free)
    embs    = np.array(_embed_batch([c["text"] for c in candidates]))  # (n, d)
    norms   = np.linalg.norm(embs, axis=1, keepdims=True)
    embs_n  = embs / np.where(norms == 0, 1.0, norms)

    q   = query_emb / (np.linalg.norm(query_emb) or 1.0)
    rel = embs_n @ q  # cosine similarity to query, shape (n,)

    selected:  List[int] = []
    remaining: List[int] = list(range(len(candidates)))

    for _ in range(min(top_k, len(candidates))):
        if not remaining:
            break
        if not selected:
            best = max(remaining, key=lambda i: rel[i])
        else:
            sel_embs = embs_n[selected]  # (k, d)
            scores: List[Tuple[int, float]] = []
            for i in remaining:
                relevance  = float(rel[i])
                redundancy = float(np.max(embs_n[i] @ sel_embs.T))
                scores.append((i, lambda_ * relevance - (1.0 - lambda_) * redundancy))
            best = max(scores, key=lambda x: x[1])[0]
        selected.append(best)
        remaining.remove(best)

    return [candidates[i] for i in selected]


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic context window  (token budget)
# ──────────────────────────────────────────────────────────────────────────────

def _fit_budget(chunks: List[Dict], budget: int = _TOKEN_BUDGET) -> List[Dict]:
    """Trim chunk list so total token estimate stays within `budget`."""
    result, used = [], 0
    for c in chunks:
        tokens = len(c["text"]) // _CHARS_PER_TOKEN
        if used + tokens > budget:
            break
        result.append(c)
        used += tokens
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Core hybrid pipeline
# ──────────────────────────────────────────────────────────────────────────────

def _hybrid_retrieve(
    query:       str,
    n_results:   int            = 8,
    filter_user: Optional[str]  = None,
    filters:     Optional[Dict] = None,
) -> List[Dict]:
    """
    Full hybrid retrieval:
    Expansion → Parallel(Vector+BM25) → RRF → Dedup
    → Rerank → Score → DocFirst → MMR → Budget
    """
    where   = _build_where(filter_user, filters)
    queries = _expand_queries(query)                        # 3–5 variants
    embeddings   = _embed_batch(queries)                    # List[np.ndarray]
    primary_emb  = embeddings[0]

    # Semantic cache check
    cached = _cache_lookup(primary_emb)
    if cached is not None:
        return cached[:n_results]

    # Parallel vector + BM25 retrieval
    ranked_lists: List[List[Dict]] = []
    max_workers = min(len(embeddings) + len(queries), 10)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        vec_futs  = [pool.submit(_vector_search, emb, _MAX_CANDIDATES, where) for emb in embeddings]
        bm25_futs = [pool.submit(_bm25_search,   q,   _MAX_CANDIDATES)        for q   in queries]

        for fut in as_completed(vec_futs + bm25_futs):
            try:
                res = fut.result()
                if res:
                    ranked_lists.append(res)
            except Exception as exc:
                log.warning(f"[Retriever] search future error: {exc}")

    if not ranked_lists:
        return []

    # RRF fusion → cap
    candidates = _rrf_merge(ranked_lists)[:_MAX_CANDIDATES]

    # Cross-encoder reranking
    candidates = _rerank(query, candidates)

    # Smart scoring
    for c in candidates:
        c["_final_score"] = _compute_final_score(c)
    candidates.sort(key=lambda c: c["_final_score"], reverse=True)

    # Document-first selection  (aggregate by doc, pick best chunks per doc)
    candidates = _document_first(candidates, top_docs=10, max_per_doc=_MAX_CHUNKS_PER_DOC)

    # MMR diversity
    candidates = _mmr(candidates, primary_emb, lambda_=_MMR_LAMBDA, top_k=n_results * 2)

    # Token budget
    candidates = _fit_budget(candidates, _TOKEN_BUDGET)

    # Format and cache
    output = [_public_chunk(c) for c in candidates[:n_results]]
    _cache_store(primary_emb, output)

    return output


# ──────────────────────────────────────────────────────────────────────────────
# ─── Public API  (fully backwards-compatible with all existing callers) ────────
# ──────────────────────────────────────────────────────────────────────────────

def retrieve_context(
    query:       str,
    n_results:   int            = 8,
    filter_user: Optional[str]  = None,
    filters:     Optional[Dict] = None,
) -> List[Dict]:
    """
    Primary retrieval entry point.
    Runs the full hybrid pipeline and returns top-k chunks.

    Args:
        query:       Natural-language question or search string.
        n_results:   Number of chunks to return.
        filter_user: Restrict to a specific user_email (Chroma metadata filter).
        filters:     Additional key→value Chroma metadata filters.
    """
    return _hybrid_retrieve(query, n_results=n_results, filter_user=filter_user, filters=filters)


def multi_retrieve_context(
    queries:     List[str],
    n_per_query: int = 6,
    final_k:     int = 10,
) -> List[Dict]:
    """
    Run the full hybrid pipeline for each query in parallel,
    merge, deduplicate, and return the top `final_k` chunks.
    """
    seen: Dict[str, Dict] = {}

    with ThreadPoolExecutor(max_workers=min(len(queries), 4)) as pool:
        futs = {pool.submit(_hybrid_retrieve, q, n_per_query): q for q in queries}
        for fut in as_completed(futs):
            try:
                for chunk in fut.result():
                    h = _text_hash(chunk["text"])
                    if h not in seen or chunk["relevance_score"] > seen[h]["relevance_score"]:
                        seen[h] = chunk
            except Exception as exc:
                log.warning(f"[MultiRetrieve] query failed: {exc}")

    return sorted(seen.values(), key=lambda c: c["relevance_score"], reverse=True)[:final_k]


def retrieve_all_chunks() -> List[Dict]:
    """Return every chunk in the collection (used for bulk / people-aware operations)."""
    col   = _get_collection()
    count = col.count()
    if count == 0:
        return []

    res    = col.get(include=["documents", "metadatas"], limit=count)
    chunks = []
    for doc, meta in zip(res["documents"], res["metadatas"]):
        c = _public_chunk(_meta_to_chunk(doc, meta))
        c["relevance_score"] = 1.0   # preserve original bulk-op semantics
        chunks.append(c)

    log.debug(f"[retrieve_all_chunks] total={len(chunks)}, "
              f"files={dict(Counter(c['filename'] for c in chunks))}")
    return chunks


def retrieve_context_for_people(
    query:         str,
    people:        List[str],
    n_results:     int  = 8,
    exclude_multi: bool = False,
) -> List[Dict]:
    """People-aware retrieval: filter by names appearing in chunk text."""
    candidates  = retrieve_all_chunks()
    lower_names = [p.lower() for p in people]

    if exclude_multi:
        person   = lower_names[0]
        filtered = []
        for c in candidates:
            names_l = [n.lower() for n in _parse_people_involved(c["text"])]
            if len(names_l) == 1 and any(
                n.startswith(person) or person.startswith(n) for n in names_l
            ):
                filtered.append(c)
    else:
        filtered = [
            c for c in candidates
            if all(name in c["text"].lower() for name in lower_names)
        ]

    return (filtered if filtered else candidates)[:n_results]


def filter_chunks_by_field(field: str, value: str, chunks: List[Dict]) -> List[Dict]:
    """Return chunks whose text contains 'field: value' (case-insensitive)."""
    pattern = re.compile(
        rf"{re.escape(field)}\s*:\s*{re.escape(value)}", re.IGNORECASE
    )
    return [c for c in chunks if pattern.search(c["text"])]


def retrieve_by_category(category: str, n_results: int = 15) -> List[Dict]:
    """Return chunks whose doc_category contains the given category string."""
    return [
        c for c in retrieve_all_chunks()
        if category.lower() in c.get("doc_category", "").lower()
    ][:n_results]


# ──────────────────────────────────────────────────────────────────────────────
# People field parser  (imported directly by llm_chain.py)
# ──────────────────────────────────────────────────────────────────────────────

def _parse_people_involved(text: str) -> List[str]:
    text_lower = text.lower()
    markers    = ["people involved:", "people:", "team members:", "members:"]
    idx, matched = -1, ""
    for marker in markers:
        idx = text_lower.find(marker)
        if idx != -1:
            matched = marker
            break
    if idx == -1:
        return []
    value_start = idx + len(matched)
    pipe_idx    = text.find(" | ", value_start)
    raw = (
        text[value_start:pipe_idx].strip()
        if pipe_idx != -1
        else text[value_start:].strip()
    )
    return [n.strip().strip('"').strip("'") for n in raw.split(",") if n.strip()]
