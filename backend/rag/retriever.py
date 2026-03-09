import re
from typing import List, Dict
from collections import Counter

from backend.db.chroma_client import get_documents_collection
from backend.ingestion.embedder import embed_texts


# ---------------------------------------------------------
# Query expansion (improves embedding quality)
# ---------------------------------------------------------

def _expand_query(query: str) -> str:
    return f"Find relevant document sections, tables, figures, charts, or text related to: {query}"


# ---------------------------------------------------------
# Distance normalization
# ---------------------------------------------------------

def _normalize_distance(dist: float) -> float:
    """
    Convert vector distance to similarity score (0-1).
    Works for cosine or L2 distances.
    """
    return 1 / (1 + dist)


# ---------------------------------------------------------
# Main retrieval
# ---------------------------------------------------------

def retrieve_context(query: str, n_results: int = 8, filter_user: str = None) -> List[Dict]:

    collection = get_documents_collection()

    expanded_query = _expand_query(query)

    query_embedding = embed_texts([expanded_query])[0]

    where_filter = {"user_email": filter_user} if filter_user else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results * 2,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    context_chunks = []

    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):

        score = _normalize_distance(dist)

        context_chunks.append({
            "text": doc,
            "user": meta.get("user_name", "Unknown"),
            "email": meta.get("user_email", ""),
            "user_id": meta.get("user_id", ""),
            "filename": meta.get("filename", ""),
            "document_type": meta.get("document_type", ""),
            "doc_category": meta.get("doc_category", ""),
            "uploaded_at": meta.get("uploaded_at", ""),
            "total_chunks": meta.get("total_chunks", 0),
            "relevance_score": round(score, 3)
        })

    context_chunks.sort(key=lambda c: c["relevance_score"], reverse=True)

    return context_chunks[:n_results]


# ---------------------------------------------------------
# Retrieve all chunks
# ---------------------------------------------------------

def retrieve_all_chunks() -> list:

    collection = get_documents_collection()

    count = collection.count()

    if count == 0:
        return []

    result = collection.get(include=["documents", "metadatas"], limit=count)

    chunks = []

    for doc, meta in zip(result["documents"], result["metadatas"]):

        chunks.append({
            "text": doc,
            "user": meta.get("user_name", "Unknown"),
            "email": meta.get("user_email", ""),
            "user_id": meta.get("user_id", ""),
            "filename": meta.get("filename", ""),
            "document_type": meta.get("document_type", ""),
            "doc_category": meta.get("doc_category", ""),
            "uploaded_at": meta.get("uploaded_at", ""),
            "total_chunks": meta.get("total_chunks", 0),
            "relevance_score": 1.0,
        })

    file_counts = Counter(c["filename"] for c in chunks)

    print(f"[retrieve_all_chunks] total={len(chunks)}, files={dict(file_counts)}")

    return chunks


# ---------------------------------------------------------
# Multi-query retrieval
# ---------------------------------------------------------

def multi_retrieve_context(
    queries: list,
    n_per_query: int = 6,
    final_k: int = 10
) -> list:

    seen = {}

    for q in queries:

        expanded_query = _expand_query(q)

        query_embedding = embed_texts([expanded_query])[0]

        collection = get_documents_collection()

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_per_query * 2,
            include=["documents", "metadatas", "distances"]
        )

        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        ):

            score = _normalize_distance(dist)

            chunk = {
                "text": doc,
                "user": meta.get("user_name", "Unknown"),
                "email": meta.get("user_email", ""),
                "user_id": meta.get("user_id", ""),
                "filename": meta.get("filename", ""),
                "document_type": meta.get("document_type", ""),
                "doc_category": meta.get("doc_category", ""),
                "uploaded_at": meta.get("uploaded_at", ""),
                "total_chunks": meta.get("total_chunks", 0),
                "relevance_score": round(score, 3)
            }

            key = doc

            if key not in seen or chunk["relevance_score"] > seen[key]["relevance_score"]:
                seen[key] = chunk

    merged = sorted(
        seen.values(),
        key=lambda c: c["relevance_score"],
        reverse=True
    )

    return merged[:final_k]


# ---------------------------------------------------------
# People field parser
# ---------------------------------------------------------

def _parse_people_involved(text: str) -> list:

    text_lower = text.lower()

    markers = ["people involved:", "people:", "team members:", "members:"]

    idx = -1
    matched_marker = ""

    for marker in markers:
        idx = text_lower.find(marker)
        if idx != -1:
            matched_marker = marker
            break

    if idx == -1:
        return []

    value_start = idx + len(matched_marker)

    pipe_idx = text.find(" | ", value_start)

    raw = (
        text[value_start:pipe_idx].strip()
        if pipe_idx != -1
        else text[value_start:].strip()
    )

    return [n.strip().strip('"').strip("'") for n in raw.split(",") if n.strip()]


# ---------------------------------------------------------
# People-aware retrieval
# ---------------------------------------------------------

def retrieve_context_for_people(
    query: str,
    people: list,
    n_results: int = 8,
    exclude_multi: bool = False
) -> list:

    candidates = retrieve_all_chunks()

    lower_names = [p.lower() for p in people]

    if exclude_multi:

        person = lower_names[0]

        filtered = []

        for c in candidates:

            names = _parse_people_involved(c["text"])

            names_lower = [n.lower() for n in names]

            if len(names_lower) == 1 and any(
                n.startswith(person) or person.startswith(n)
                for n in names_lower
            ):
                filtered.append(c)

    else:

        filtered = [
            c for c in candidates
            if all(name in c["text"].lower() for name in lower_names)
        ]

    results = filtered if filtered else candidates

    return results[:n_results]


# ---------------------------------------------------------
# Filter chunks by a text field value
# ---------------------------------------------------------

def filter_chunks_by_field(field: str, value: str, chunks: list) -> list:
    """Return chunks whose text contains 'field: value' (case-insensitive)."""
    pattern = re.compile(
        rf"{re.escape(field)}\s*:\s*{re.escape(value)}",
        re.IGNORECASE
    )
    return [c for c in chunks if pattern.search(c["text"])]


# ---------------------------------------------------------
# Retrieve chunks by doc_category
# ---------------------------------------------------------

def retrieve_by_category(category: str, n_results: int = 15) -> list:
    """Return chunks whose doc_category contains the given category string."""
    all_chunks = retrieve_all_chunks()
    filtered = [
        c for c in all_chunks
        if category.lower() in c.get("doc_category", "").lower()
    ]
    return filtered[:n_results]