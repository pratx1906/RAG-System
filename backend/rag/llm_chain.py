import ollama
import json
import re
from backend.config import OLLAMA_MODEL
from typing import List, Dict, Optional
from backend.rag.retriever import (
    retrieve_context, multi_retrieve_context, retrieve_context_for_people,
    retrieve_all_chunks, filter_chunks_by_field, _parse_people_involved,
    retrieve_by_category,
)
from backend.db.chroma_client import get_documents_collection


# ── Preserved functions (signatures and behavior unchanged) ─────────────────────

def _call_ollama(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = ollama.chat(model=OLLAMA_MODEL, messages=messages)
    return response["message"]["content"]


def generate_project_summary(chunks: List[str], contributor_names: List[str]) -> Dict:
    """Use LLM to infer a project name, description and keywords from document chunks."""
    combined = "\n\n---\n\n".join(chunks)
    contributors_str = ", ".join(contributor_names) if contributor_names else "Unknown"

    system = (
        "You are an expert project analyst. Your job is to analyze document excerpts "
        "and identify the underlying project they belong to. Be concise and precise. "
        "Always respond with valid JSON only. No markdown, no explanation."
    )

    prompt = f"""
The following document excerpts were written by: {contributors_str}

EXCERPTS:
{combined}

Based on these excerpts, identify:
1. A short descriptive project name (3-6 words max)
2. A 2-3 sentence description of what this project is about
3. 5-8 keywords that characterize this project

Return ONLY this JSON structure:
{{
  "project_name": "...",
  "description": "...",
  "keywords": ["...", "..."]
}}
"""
    raw = _call_ollama(prompt, system)
    # Strip any accidental markdown fences
    raw = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "project_name": "Unnamed Project",
            "description": raw[:300],
            "keywords": []
        }


def generate_query_variants(query: str, n: int = 3) -> list:
    """Ask the LLM to produce n alternative phrasings of the query."""
    system = "You are an expert at reformulating search queries. Output ONLY a JSON array of strings, no explanation."
    prompt = (
        f"Generate {n} different ways to ask the following question. "
        f"Vary the wording and focus. Include the original as the first item.\n\n"
        f"Question: {query}\n\n"
        f'Return ONLY a JSON array like: ["...", "...", "..."]'
    )
    raw = _call_ollama(prompt, system)
    raw = re.sub(r"```json|```", "", raw).strip()
    try:
        variants = json.loads(raw)
        if isinstance(variants, list) and all(isinstance(v, str) for v in variants):
            return variants[:n]
    except (json.JSONDecodeError, ValueError):
        pass
    return [query]  # fallback: just use original


# ── Dynamic team roster ──────────────────────────────────────────────────────────

def _get_team_roster() -> list:
    """
    Build team roster from two sources:
    1. user_name metadata (uploaders)
    2. Names found in 'People involved' fields across all chunks
    This ensures people mentioned in documents but who haven't
    uploaded files are still recognised in queries.
    """
    from backend.rag.retriever import retrieve_all_chunks, _parse_people_involved
    names = set()
    try:
        # Source 1: uploaders from metadata
        collection = get_documents_collection()
        result = collection.get(include=["metadatas"])
        for meta in result.get("metadatas", []):
            user_name = meta.get("user_name", "").strip()
            if user_name:
                first = user_name.split()[0].lower()
                names.add(first)

        # Source 2: names from People involved fields in all chunks
        chunks = retrieve_all_chunks()
        for chunk in chunks:
            for person in _parse_people_involved(chunk["text"]):
                first = person.strip().split()[0].lower()
                if first and len(first) > 1:
                    names.add(first)

    except Exception as e:
        print(f"[_get_team_roster] error: {e}")
    return list(names)


def _extract_people(query: str, roster: list) -> list:
    """Return roster first names found in the query (lowercase, deduplicated)."""
    q = query.lower()
    return list({name for name in roster if name in q})


def _extract_potential_people(query: str, roster: list) -> tuple:
    """
    Returns (known_people, unknown_people) found in query.

    known_people: roster first-names found in query (lowercase).
    unknown_people: capitalised words that look like person names but
                    are not in the roster and not common English words.
    Used to detect queries like "Anoushka and John" where John is unknown.
    """
    COMMON_WORDS = {
        "what", "which", "who", "how", "where", "when", "why",
        "project", "projects", "working", "work", "on", "is", "are",
        "the", "a", "an", "and", "or", "not", "in", "of", "to",
        "do", "does", "list", "all", "together", "with", "for",
        "their", "they", "them", "status", "category",
    }
    known = _extract_people(query, roster)
    words = query.split()
    unknown = []
    for w in words:
        clean = w.strip("?.,!").lower()
        if (
            w[0].isupper()
            and clean not in COMMON_WORDS
            and clean not in roster
            and len(clean) > 2
            and clean not in [p.lower() for p in known]
        ):
            unknown.append(clean)
    return known, list(set(unknown))


_KNOWN_STATUS_VALUES = [
    "not yet started",
    "not started",
    "in progress",
    "initiated",
    "completed",
    "cancelled",
]


def extract_status_filter(query: str) -> Optional[str]:
    """
    Return the first known status value found in the query (case-insensitive),
    or None if the query does not mention a specific status.
    Longer phrases are checked first to avoid partial matches.
    """
    q = query.lower()
    for status in sorted(_KNOWN_STATUS_VALUES, key=len, reverse=True):
        if status in q:
            return status
    return None


# ── Intent classification ────────────────────────────────────────────────────────

_NEGATION_WORDS = {
    "not", "without", "except", "excluding", "never", "no one", "nobody", "outside",
}
_SOLO_WORDS = {
    "alone", "solo", "independently", "by themselves", "by herself", "by himself",
    "on their own", "on her own", "on his own", "only", "just", "herself", "himself",
    "by oneself", "single-handedly",
}
_AGGREGATE_WORDS = {
    "list", "all", "every", "count", "overview", "summary", "total",
    "how many", "enumerate", "across all", "everyone", "everything",
    "whole", "full list", "entire",
    "category", "categories", "breakdown", "distribution", "group by",
    "more than", "only one", "one person", "single person",
    "how many people", "most people",
    # FIX 7: who has the most / most projects routing
    "who has the most", "most projects", "busiest", "most involved",
    "highest number of projects",
}
_TEMPORAL_WORDS = {
    "when", "deadline", "date", "schedule", "timeline", "due", "by when",
}
_STATUS_WORDS = {
    "status", "progress", "update", "state", "current", "done", "finished", "complete",
}
_COMPARE_WORDS = {
    "compare", "difference", "versus", "vs", "contrast", "differ", "similar", "between",
}
_CAUSAL_WORDS = {
    "why", "reason", "cause", "because", "led to", "result in", "explain why",
}
_DEFINITION_WORDS = {
    "what is", "what are", "explain", "describe", "definition", "define", "meaning",
}


def _classify_intent(query: str, roster: list) -> tuple:
    """
    Classify query into one of 11 intents via structural keyword matching.
    Extracts people from the roster internally.

    Returns (intent_str, people_list) where people_list is the list of
    known (and possibly unknown) person names relevant to the query.

    Priority (checked top to bottom, stops at first match):
      STATUS (known value) > NEGATION > INTERSECTION (known+unknown) >
      INTERSECTION (2+ known) > SOLO > AGGREGATE >
      TEMPORAL > STATUS (keyword) > COMPARATIVE > CAUSAL > PERSON >
      DEFINITION > UNKNOWN PERSON > GENERAL
    """
    q = query.lower()
    has_negation = any(w in q for w in _NEGATION_WORDS)
    has_compare = any(w in q for w in _COMPARE_WORDS)

    # Extract people: known from roster + detect unknown capitalised names
    people, unknown_people = _extract_potential_people(query, roster)

    # 0. STATUS priority override: if the query contains a known status value
    # (e.g. "not yet started", "in progress") classify as STATUS immediately.
    # This prevents "not" triggering NEGATION and "how many" triggering AGGREGATE.
    if extract_status_filter(query):
        return "STATUS", people

    # 1. NEGATION: negation words + at least one known person name
    if has_negation and len(people) >= 1:
        return "NEGATION", people

    # 2a. INTERSECTION: 1 known person + 1+ unknown person-like words
    # Handles "Anoushka and John" where John is not in roster
    if len(people) >= 1 and len(unknown_people) >= 1:
        return "INTERSECTION", people + unknown_people

    # 2b. INTERSECTION: 2+ known people (COMPARATIVE if compare words present)
    if len(people) >= 2:
        return ("COMPARATIVE" if has_compare else "INTERSECTION"), people

    # 3. SOLO: 1 person + solo words
    if len(people) == 1 and any(w in q for w in _SOLO_WORDS):
        return "SOLO", people

    # 4. AGGREGATE — skip if a person is mentioned
    if any(w in q for w in _AGGREGATE_WORDS) and len(people) == 0:
        return "AGGREGATE", people

    # 5. TEMPORAL
    if any(w in q for w in _TEMPORAL_WORDS):
        return "TEMPORAL", people

    # 6. STATUS (keyword fallback)
    if any(w in q for w in _STATUS_WORDS):
        return "STATUS", people

    # 7. COMPARATIVE (no person required)
    if has_compare:
        return "COMPARATIVE", people

    # 8. CAUSAL
    if any(w in q for w in _CAUSAL_WORDS):
        return "CAUSAL", people

    # 9. PERSON: 1 known person, no special keywords matched above
    # Checked before DEFINITION so "What is Anoushka working on?" → PERSON not DEFINITION
    if len(people) == 1:
        return "PERSON", people

    # 10. DEFINITION — only when no person is mentioned
    if any(w in q for w in _DEFINITION_WORDS) and len(people) == 0:
        return "DEFINITION", people

    # 11. Unknown person with no known people — treat as person query ONLY for
    # person-pattern queries. Category words like "hackathon" also trigger
    # unknown_people but must not be routed to PERSON. (FIX 4)
    _PERSON_QUERY_PATTERNS = [
        "what projects is", "what is", "what does",
        "working on alone", "tell me about",
    ]
    _is_person_pattern = any(p in q for p in _PERSON_QUERY_PATTERNS)
    if len(unknown_people) >= 1 and len(people) == 0 and _is_person_pattern:
        return "PERSON", unknown_people

    # 12. GENERAL catch-all
    return "GENERAL", people


# ── Retrieval routing ────────────────────────────────────────────────────────────

def _all_chunks_or_fallback(query: str) -> list:
    """Return all chunks from ChromaDB; falls back to broad semantic retrieval if empty."""
    result = retrieve_all_chunks()
    return result or retrieve_context(query, n_results=50)


def _route_retrieval(intent: str, query: str, people: list, variants: list) -> list:
    """
    Route retrieval to the appropriate strategy based on intent.
    Every path has a graceful fallback so results are never empty unless ChromaDB is empty.
    """
    if intent == "NEGATION":
        return _all_chunks_or_fallback(query)

    if intent == "AGGREGATE":
        return _all_chunks_or_fallback(query)

    if intent == "INTERSECTION":
        # Scan all chunks to avoid missing valid pairs due to semantic ranking
        all_c = retrieve_all_chunks()
        if all_c:
            lower_names = [p.lower() for p in people]
            filtered = [
                c for c in all_c
                if all(name in c["text"].lower() for name in lower_names)
            ]
            if filtered:
                return filtered
        # Fallback to semantic if full scan finds nothing (e.g. unknown person)
        chunks = retrieve_context_for_people(query, people, n_results=15)
        if not chunks:
            chunks = multi_retrieve_context(variants, n_per_query=6, final_k=15)
        return chunks

    if intent == "SOLO":
        # Directly filter the full dataset so we never inherit the fallback-to-all
        # behaviour inside retrieve_context_for_people. Returns empty list when
        # no solo chunks exist — triggers Python-level message in answer_query.
        if not people:
            return []
        person = people[0].lower()
        all_c = retrieve_all_chunks()
        solo_chunks = []
        for c in all_c:
            names = _parse_people_involved(c["text"])
            names_lower = [n.lower() for n in names]
            if len(names_lower) == 1 and any(
                n.startswith(person) or person.startswith(n)
                for n in names_lower
            ):
                solo_chunks.append(c)
        return solo_chunks

    if intent == "PERSON":
        # FIX 6: Full-scan for person rather than capped semantic retrieval.
        # This ensures all chunks mentioning the person are returned, not just top-15.
        if people:
            person = people[0].lower()
            all_c = retrieve_all_chunks()
            if all_c:
                person_chunks = [
                    c for c in all_c
                    if person in c["text"].lower()
                ]
                if person_chunks:
                    return person_chunks
        chunks = retrieve_context_for_people(query, people, n_results=25)
        if not chunks:
            chunks = multi_retrieve_context(variants, n_per_query=6, final_k=25)
        return chunks

    if intent in ("STATUS", "TEMPORAL", "COMPARATIVE"):
        chunks = _all_chunks_or_fallback(query)
        if intent == "STATUS":
            status_value = extract_status_filter(query)
            if status_value:
                filtered = filter_chunks_by_field("Status", status_value, chunks)
                if filtered:
                    chunks = filtered
        if not chunks:
            chunks = multi_retrieve_context(variants, n_per_query=6, final_k=15)
        return chunks

    # CAUSAL, DEFINITION, GENERAL
    # FIX 3: For category queries, retrieve only matching category chunks first.
    _CATEGORY_ROUTE_WORDS = [
        "hackathon", "cuas", "sdr", "comint", "hardware", "idex",
        "internal tool", "pdw", "iq data", "rf data", "display system",
    ]
    _matched_route_cat = next(
        (c for c in _CATEGORY_ROUTE_WORDS if c in query.lower()), None
    )
    if _matched_route_cat:
        cat_chunks = retrieve_by_category(_matched_route_cat)
        if cat_chunks:
            return cat_chunks

    # Use full dataset ranked so semantically relevant chunks come first.
    # This ensures category/grouping queries see all chunks, not just top-k.
    semantic = multi_retrieve_context(variants, n_per_query=6, final_k=15)
    all_c = retrieve_all_chunks()
    if all_c:
        sem_texts = {c["text"] for c in semantic}
        ranked = sorted(all_c, key=lambda c: c["text"] not in sem_texts)
        return ranked[:30]
    return semantic


# ── System prompt construction ───────────────────────────────────────────────────

_PART_A = """You are a knowledge assistant. Your answers must be grounded EXCLUSIVELY in the source documents provided.

UNIVERSAL RULES — NEVER VIOLATE:
1. Only state facts explicitly written in the source text. Do not infer, extrapolate, or assume.
2. Never use outside knowledge to fill gaps. If a fact is absent, say: "This information is not in the knowledge base."
3. Never mention any person not listed in PEOPLE PRESENT IN SOURCES.
4. Never fabricate names, dates, tasks, or relationships not present in source text.
5. Cite every claim with [Source N]. A claim without a citation is not allowed.
6. If sources conflict, flag the conflict explicitly and cite both sides.
7. If sources are insufficient to fully answer, state exactly what information is missing."""

_INTENT_INSTRUCTIONS: Dict[str, str] = {
    "NEGATION": (
        "Step 1: List ALL items found across every source chunk.\n"
        "Step 2: List only items where the specified person IS explicitly mentioned.\n"
        "Step 3: The answer is Step 1 minus Step 2 — items NOT involving that person.\n"
        "Do not include any item unless it appears explicitly in a source chunk."
    ),
    "INTERSECTION": (
        "Scan every source chunk. For each chunk, check if ALL queried person names "
        "appear in the 'People involved' field of that chunk. List only projects where "
        "ALL names appear together in the same chunk's People involved field. "
        "After your list, write nothing else — no summary, no conclusion sentence."
    ),
    "SOLO": (
        "SOLO QUERY — you have been given pre-filtered source chunks where "
        "the People involved field contains exactly ONE person.\n"
        "Your job:\n"
        "1. For each source chunk, read the Project name\n"
        "2. Read the People involved field — it should contain one name\n"
        "3. If that one name matches the person being asked about, include "
        "that project in your answer\n"
        "4. List every project that passes step 3\n"
        "5. If no chunks pass step 3, say: "
        "'No solo projects found for [name] in the knowledge base.'\n"
        "Do not second-guess the pre-filtering. If a chunk was provided, "
        "its People involved field has already been verified to contain "
        "exactly one name."
    ),
    "AGGREGATE": (
        "Process every source chunk. Collect all items across all chunks. "
        "Deduplicate before answering. Present a complete, consolidated list."
    ),
    "TEMPORAL": (
        "Only report dates, deadlines, or timelines that are EXPLICITLY written in the sources. "
        "Do not infer or estimate any date not directly stated in a source chunk. "
        "IMPORTANT: Do not infer 'overdue' or 'late' status — the sources contain no 'overdue' "
        "field. If asked about overdue projects, state: 'No project is explicitly marked as "
        "overdue in the knowledge base.'"
    ),
    "STATUS": (
        "STATUS QUERY — STRICT RULES:\n"
        "- The chunks have already been pre-filtered by status value where possible.\n"
        "- For each source chunk, read the exact text after 'Status:' up to the next '|' character. "
        "That is the status. Do not infer it from anywhere else.\n"
        "- Only list a project under a status if its chunk explicitly shows that status.\n"
        "- Count only after listing. Do not estimate or round."
    ),
    "COMPARATIVE": (
        "Compare dimension by dimension. For each dimension, state what each side says and cite each side separately. "
        "Do not blend or average — keep each perspective distinct."
    ),
    "CAUSAL": (
        "Only state causes or reasons that are explicitly documented in the sources. "
        "Do not infer causality from correlation or proximity in the text."
    ),
    "DEFINITION": (
        "Only use definitions or descriptions that are directly present in the sources. "
        "Do not supplement with outside knowledge or general understanding."
    ),
    "PERSON": (
        "Read every source chunk from [Source 1] to the last source. "
        "For each chunk, check the 'People involved' field. If the queried person "
        "appears in that field, include that project in your answer. "
        "Process ALL sources — do not stop early, do not skip any source number. "
        "List every project you find."
    ),
    "GENERAL": (
        "Answer using only the provided sources. Synthesize across chunks where relevant. "
        "State any gaps or missing information clearly."
    ),
}


def _build_system_prompt(intent: str) -> str:
    instruction = _INTENT_INSTRUCTIONS.get(intent, _INTENT_INSTRUCTIONS["GENERAL"])
    return f"{_PART_A}\n\nINTENT-SPECIFIC INSTRUCTION ({intent}):\n{instruction}"


# ── Post-processing helpers ──────────────────────────────────────────────────────

def _strip_hallucinated_tail(text: str) -> str:
    """
    Remove common LLM tail phrases that contradict a valid answer.
    gemma3:4b sometimes appends these after a complete response.
    """
    TAIL_PHRASES = [
        "this information is not in the knowledge base",
        "this information is not available in the knowledge base",
        "this information is not available",
        "no relevant documents found",
        "i cannot find this information",
        "i don't have information about this",
        "i do not have information about this",
        "i don't have information",
        "i do not have information",
        "based on the available sources, i cannot",
        "unfortunately, i cannot",
        "there is no mention of",
    ]
    lines = text.strip().split("\n")
    while lines:
        last = lines[-1].strip().lower().rstrip(".")
        if any(phrase in last for phrase in TAIL_PHRASES):
            lines.pop()
        else:
            break
    return "\n".join(lines).strip()


# ── Chunk utility helpers ────────────────────────────────────────────────────────

def _extract_field(text: str, field: str) -> str:
    """Extract value of a named field from pipe-delimited chunk text."""
    idx = text.lower().find(field.lower() + ":")
    if idx == -1:
        return ""
    start = idx + len(field) + 1
    end = text.find(" | ", start)
    return text[start:end].strip() if end != -1 else text[start:].strip()


def _extract_from_structured_line(chunk_text: str, field: str) -> str:
    """Extract field value from the structured (first) line of a dual-rep chunk.
    Falls back to full text if the field is not found on the first line."""
    first_line = chunk_text.split("\n")[0]
    result = _extract_field(first_line, field)
    if not result:
        result = _extract_field(chunk_text, field)
    return result


def _dedup_by_project(chunks: list) -> list:
    """Keep only the first chunk seen for each unique Project value."""
    seen_projects: set = set()
    deduped = []
    for c in chunks:
        project = _extract_from_structured_line(c["text"], "Project").lower().strip()
        if project and project not in seen_projects:
            seen_projects.add(project)
            deduped.append(c)
        elif not project:
            deduped.append(c)
    return deduped


# ── Main query pipeline ──────────────────────────────────────────────────────────

def answer_query(query: str, user_email: str = None) -> Dict:
    """
    Full RAG pipeline:
    1. Build dynamic team roster from ChromaDB metadata
    2. Classify query intent via keyword matching
    3. Generate query variants for semantic recall
    4. Route retrieval based on intent
    5. Build intent-aware prompt and call LLM
    6. Return structured response with answer, intent, and sources
    """
    # Step 1: dynamic roster + people detection
    roster = _get_team_roster()

    # Step 2: intent classification (extracts people from roster internally)
    intent, people = _classify_intent(query, roster)

    # Step 3: query variants (used by most retrieval paths)
    variants = generate_query_variants(query, n=3)

    # Step 4: retrieval routing
    chunks = _route_retrieval(intent, query, people, variants)

    # Short-circuit 1: SOLO or general empty
    if not chunks:
        if intent == "SOLO" and people:
            person_name = people[0].capitalize()
            return {
                "answer": f"No projects found where {person_name} is the sole person involved. "
                          f"Either {person_name} only works in teams, or there are no documents "
                          f"about {person_name} in the knowledge base.",
                "query_intent": intent,
                "sources": [],
            }
        return {
            "answer": "No relevant documents found in the knowledge base. Please ask team members to upload their work.",
            "query_intent": intent,
            "sources": [],
        }

    # Short-circuit: Unknown PERSON — not in knowledge base
    # Placed early so we don't build context or call LLM for absent people.
    roster_lower = [r.lower() for r in roster]
    if intent == "PERSON" and people:
        unknown_queried = [p for p in people if p.lower() not in roster_lower]
        if unknown_queried and len(unknown_queried) == len(people):
            return {
                "answer": (
                    f"There is no mention of '{people[0].capitalize()}' "
                    f"in the knowledge base."
                ),
                "query_intent": intent,
                "sources": [],
            }

    # Short-circuit: PERSON — Python directly extracts all person's projects from
    # People involved field. Avoids LLM skipping chunks (fixes Q14, Q15).
    if intent == "PERSON" and people:
        known_queried = [p for p in people if p.lower() in roster_lower]
        if known_queried:
            person_q = known_queried[0].lower()
            person_projects: list = []
            seen_pp: set = set()
            for c in chunks:
                people_field = _extract_from_structured_line(c["text"], "People involved").lower()
                if person_q not in people_field:
                    continue
                proj = _extract_from_structured_line(c["text"], "Project").strip()
                if proj and proj.lower() not in seen_pp:
                    seen_pp.add(proj.lower())
                    person_projects.append(proj)
            if person_projects:
                formatted = "\n".join(f"* {p}" for p in person_projects)
                return {
                    "answer": (
                        f"{known_queried[0].capitalize()} is working on the following "
                        f"projects:\n{formatted}"
                    ),
                    "query_intent": intent,
                    "sources": [
                        {
                            "user": c["user"],
                            "email": c["email"],
                            "filename": c["filename"],
                            "document_type": c.get("document_type", ""),
                            "doc_category": c.get("doc_category", ""),
                            "relevance": c["relevance_score"],
                            "uploaded_at": c["uploaded_at"],
                        }
                        for c in chunks
                    ],
                }

    # Deduplicate by Project for aggregate-style intents before building context
    query_lower = query.lower()
    status_value: Optional[str] = extract_status_filter(query)
    if intent in ("STATUS", "AGGREGATE", "NEGATION"):
        chunks = _dedup_by_project(chunks)

    # Authoritative count for AGGREGATE/STATUS so LLM doesn't miscount
    TABULAR_INTENTS = ("STATUS", "AGGREGATE", "NEGATION")
    authoritative_count = len(chunks) if intent in TABULAR_INTENTS else None
    count_note = (
        f"\nAUTHORITATIVE COUNT: There are exactly {authoritative_count} "
        f"unique items in the sources after deduplication. "
        f"Your count must match this number exactly.\n"
    ) if authoritative_count is not None else ""

    # Short-circuit 2: STATUS with known status value — Python has exact answer
    if intent == "STATUS" and status_value:
        project_list = []
        seen_proj_lower: set = set()
        for c in chunks:
            proj = _extract_from_structured_line(c["text"], "Project").strip()
            if proj and proj.lower() not in seen_proj_lower:
                seen_proj_lower.add(proj.lower())
                project_list.append(proj)
        if project_list:
            formatted = "\n".join(f"* {p}" for p in project_list)
            count = len(project_list)
            return {
                "answer": (
                    f"Projects with status '{status_value}' "
                    f"({count} total):\n{formatted}"
                ),
                "query_intent": intent,
                "sources": [
                    {
                        "user": c["user"],
                        "email": c["email"],
                        "filename": c["filename"],
                        "document_type": c.get("document_type", ""),
                        "doc_category": c.get("doc_category", ""),
                        "relevance": c["relevance_score"],
                        "uploaded_at": c["uploaded_at"],
                    }
                    for c in chunks
                ],
            }

    # Pre-compute negation result so the LLM only needs to format/cite it
    negation_precomputed = ""
    if intent == "NEGATION" and people:
        person = people[0]
        person_projects: list = []
        all_projects: list = []
        for c in chunks:
            proj = _extract_from_structured_line(c["text"], "Project").strip()
            if not proj:
                continue
            if proj not in all_projects:
                all_projects.append(proj)
            # Extract people involved from structured line only
            first_line = c["text"].split("\n")[0]
            idx = first_line.lower().find("people involved:")
            if idx != -1:
                val_start = idx + len("people involved:")
                pipe = first_line.find(" | ", val_start)
                people_str_raw = (
                    first_line[val_start:pipe].strip()
                    if pipe != -1
                    else first_line[val_start:].strip()
                )
                names_in_chunk = [n.strip() for n in people_str_raw.split(",") if n.strip()]
                if any(n.lower().startswith(person) or person.startswith(n.lower()) for n in names_in_chunk):
                    if proj not in person_projects:
                        person_projects.append(proj)
        not_involved = [p for p in all_projects if p not in person_projects]
        negation_precomputed = (
            f"\nPRE-COMPUTED NEGATION RESULT (verified from source data):\n"
            f"All projects: {', '.join(all_projects)}\n"
            f"Projects {person.capitalize()} IS involved in: {', '.join(person_projects)}\n"
            f"Projects {person.capitalize()} is NOT involved in: {', '.join(not_involved)}\n"
            f"Your answer must match this pre-computed result exactly. "
            f"Cite each project with its [Source N] from the chunks below.\n"
        )

    # Short-circuit 3: NEGATION — Python not_involved list is exact (FIX 2)
    if intent == "NEGATION" and negation_precomputed and people:
        not_line = ""
        for line in negation_precomputed.split("\n"):
            if "is NOT involved in:" in line:
                not_line = line.split("NOT involved in:")[-1].strip()
                break
        if not_line:
            not_projects = [p.strip() for p in not_line.split(",") if p.strip()]
            formatted = "\n".join(f"* {p}" for p in not_projects)
            return {
                "answer": (
                    f"{people[0].capitalize()} is not involved in the "
                    f"following projects:\n{formatted}"
                ),
                "query_intent": intent,
                "sources": [
                    {
                        "user": c["user"],
                        "email": c["email"],
                        "filename": c["filename"],
                        "document_type": c.get("document_type", ""),
                        "doc_category": c.get("doc_category", ""),
                        "relevance": c["relevance_score"],
                        "uploaded_at": c["uploaded_at"],
                    }
                    for c in chunks[:5]
                ],
            }

    # Pre-compute intersection result — filter chunks by People involved field
    # (not just substring in full text) to avoid false positives.
    intersection_shared_projects: Optional[list] = None  # None = not computed
    intersection_precomputed = ""  # kept for LLM prompt injection (fallback path)
    if intent == "INTERSECTION" and len(people) >= 2:
        shared: list = []
        seen_proj: set = set()
        for c in chunks:
            # Verify ALL queried people appear in the People involved field
            people_field = _extract_from_structured_line(c["text"], "People involved").lower()
            if not all(p.lower() in people_field for p in people):
                continue
            proj = _extract_from_structured_line(c["text"], "Project").strip()
            if proj and proj.lower() not in seen_proj:
                seen_proj.add(proj.lower())
                shared.append(proj)
        intersection_shared_projects = shared

    # Short-circuit 5: INTERSECTION — Python shared list is exact
    if intersection_shared_projects is not None:
        names_display = " and ".join(p.capitalize() for p in people[:2])
        if not intersection_shared_projects:
            return {
                "answer": f"No projects found where {names_display} appear "
                          f"together in the knowledge base.",
                "query_intent": intent,
                "sources": [],
            }
        else:
            formatted = "\n".join(f"* {p}" for p in intersection_shared_projects)
            return {
                "answer": (
                    f"{names_display} work together on the following "
                    f"projects:\n{formatted}"
                ),
                "query_intent": intent,
                "sources": [
                    {
                        "user": c["user"],
                        "email": c["email"],
                        "filename": c["filename"],
                        "document_type": c.get("document_type", ""),
                        "doc_category": c.get("doc_category", ""),
                        "relevance": c["relevance_score"],
                        "uploaded_at": c["uploaded_at"],
                    }
                    for c in chunks
                ],
            }

    # Short-circuit 6: List-all AGGREGATE — Python full project list (FIX 5)
    is_list_all_query = (
        intent == "AGGREGATE"
        and any(w in query_lower for w in ["list", "all projects", "every project",
                                            "full list", "entire list", "enumerate"])
        and not any(w in query_lower for w in ["category", "categories", "status",
                                                "people", "person", "who"])
    )
    if is_list_all_query:
        all_project_names = []
        seen_lower: set = set()
        for c in chunks:
            proj = _extract_from_structured_line(c["text"], "Project").strip()
            if proj and proj.lower() not in seen_lower:
                seen_lower.add(proj.lower())
                all_project_names.append(proj)
        if all_project_names:
            formatted = "\n".join(f"* {p}" for p in all_project_names)
            return {
                "answer": (
                    f"All projects in the knowledge base "
                    f"({len(all_project_names)} total):\n{formatted}"
                ),
                "query_intent": intent,
                "sources": [
                    {
                        "user": c["user"],
                        "email": c["email"],
                        "filename": c["filename"],
                        "document_type": c.get("document_type", ""),
                        "doc_category": c.get("doc_category", ""),
                        "relevance": c["relevance_score"],
                        "uploaded_at": c["uploaded_at"],
                    }
                    for c in chunks[:5]
                ],
            }

    # Block 2: category_precomputed — people working on a given category
    CATEGORY_WORDS = [
        "hackathon", "cuas", "sdr", "comint", "hardware", "idex",
        "internal tool", "pdw", "iq data", "rf data", "display system",
        "academic", "research",
    ]
    matched_category = next(
        (cat for cat in CATEGORY_WORDS if cat in query_lower), None
    )
    category_precomputed = ""
    if matched_category and any(
        w in query_lower
        for w in ["who", "working", "involved", "people", "team", "list"]
    ):
        category_people: dict = {}
        for c in chunks:
            cat = _extract_from_structured_line(c["text"], "Category").lower().strip()
            if matched_category in cat:
                proj = _extract_from_structured_line(c["text"], "Project").strip()
                people_raw = _extract_from_structured_line(c["text"], "People involved").strip()
                if proj:
                    category_people[proj] = people_raw or "Not listed"
        if category_people:
            category_precomputed = (
                f"\nPRE-COMPUTED CATEGORY LOOKUP for '{matched_category}':\n"
                + "\n".join(f"  {p}: {ppl}" for p, ppl in category_people.items())
                + "\nUse this exact data. Cite each project with its [Source N].\n"
            )

    # Short-circuit 9: category people query — Python has exact answer (FIX 1: bug fixed)
    if category_precomputed and matched_category:
        lines = category_precomputed.strip().split("\n")
        project_lines = [
            l.strip() for l in lines
            if l.startswith("  ") and "PRE-COMPUTED" not in l
            and "Use this" not in l
        ]
        if project_lines:
            formatted = "\n".join(f"* {l}" for l in project_lines)
            return {
                "answer": (
                    f"Projects in the '{matched_category.upper()}' category "
                    f"and who is working on them:\n{formatted}"
                ),
                "query_intent": intent,
                "sources": [
                    {
                        "user": c["user"],
                        "email": c["email"],
                        "filename": c["filename"],
                        "document_type": c.get("document_type", ""),
                        "doc_category": c.get("doc_category", ""),
                        "relevance": c["relevance_score"],
                        "uploaded_at": c["uploaded_at"],
                    }
                    for c in chunks[:5]
                ],
            }

    # Block 3: people_count_precomputed — projects with N people involved
    people_count_precomputed = ""
    is_people_count_query = (
        any(w in query_lower for w in [
            "more than", "only one", "single", "more than 2", "more than two",
            "at least", "exactly one", "how many people", "one person",
        ])
        and any(w in query_lower for w in [
            "people", "person", "involved", "members",
        ])
    )
    if is_people_count_query:
        project_people_counts = []
        for c in chunks:
            proj = _extract_from_structured_line(c["text"], "Project").strip()
            people_raw = _extract_from_structured_line(c["text"], "People involved").strip()
            if proj and people_raw:
                names = [n.strip() for n in people_raw.split(",") if n.strip()]
                project_people_counts.append((proj, len(names), people_raw))

        if "more than 2" in query_lower or "more than two" in query_lower:
            filtered_counts = [(p, n, r) for p, n, r in project_people_counts if n > 2]
            count_label = "more than 2 people"
        elif any(w in query_lower for w in ["only one", "one person", "single"]):
            filtered_counts = [(p, n, r) for p, n, r in project_people_counts if n == 1]
            count_label = "exactly 1 person"
        else:
            filtered_counts = project_people_counts
            count_label = "people count"

        if filtered_counts:
            people_count_precomputed = (
                f"\nPRE-COMPUTED PEOPLE COUNT — projects with {count_label}:\n"
                + "\n".join(f"  {p} ({n} people: {r})" for p, n, r in filtered_counts)
                + "\nUse this exact list. Do not add or remove any project.\n"
            )
        else:
            people_count_precomputed = (
                f"\nPRE-COMPUTED PEOPLE COUNT: No projects found with {count_label}.\n"
            )

    # Short-circuit 7: Python has exact people-count answer — skip LLM entirely
    if people_count_precomputed and "No projects found" not in people_count_precomputed:
        lines = people_count_precomputed.strip().split("\n")
        project_lines = [
            l.strip() for l in lines
            if l.startswith("  ") and "PRE-COMPUTED" not in l and "Use this" not in l
        ]
        if project_lines:
            formatted = "\n".join(f"* {l}" for l in project_lines)
            return {
                "answer": f"Based on the knowledge base:\n{formatted}",
                "query_intent": intent,
                "sources": [
                    {
                        "user": c["user"],
                        "email": c["email"],
                        "filename": c["filename"],
                        "document_type": c.get("document_type", ""),
                        "doc_category": c.get("doc_category", ""),
                        "relevance": c["relevance_score"],
                        "uploaded_at": c["uploaded_at"],
                    }
                    for c in chunks[:5]
                ],
            }

    # Block 4: most_projects_precomputed — who has the most projects
    most_projects_precomputed = ""
    # Exclude "most projects" when query is about categories (e.g. Q18: "which category has the most projects?")
    if any(phrase in query_lower for phrase in [
        "most projects", "most work", "most tasks", "busiest",
        "most involved", "highest number", "most assignments",
    ]) and "category" not in query_lower and "categories" not in query_lower:
        person_project_map: dict = {}
        for c in chunks:
            proj = _extract_from_structured_line(c["text"], "Project").strip()
            people_raw = _extract_from_structured_line(c["text"], "People involved").strip()
            if proj and people_raw:
                for name in [n.strip() for n in people_raw.split(",") if n.strip()]:
                    first = name.split()[0]
                    person_project_map.setdefault(first, set()).add(proj)
        if person_project_map:
            ranked = sorted(
                person_project_map.items(),
                key=lambda x: len(x[1]), reverse=True
            )
            most_projects_precomputed = (
                "\nPRE-COMPUTED PROJECT COUNTS PER PERSON:\n"
                + "\n".join(f"  {name}: {len(projs)} projects"
                            for name, projs in ranked)
                + f"\nThe person with the most projects is: {ranked[0][0]} "
                  f"({len(ranked[0][1])} projects).\n"
                  "Your answer must match this exactly.\n"
            )

    # Short-circuit: most_projects — Python has exact ranked list, skip LLM
    if most_projects_precomputed:
        lines_mp = most_projects_precomputed.strip().split("\n")
        ranked_lines = [l.strip() for l in lines_mp if l.startswith("  ")]
        leader_line = next((l.strip() for l in lines_mp if "person with the most" in l), "")
        if ranked_lines and leader_line:
            ranking_str = "\n".join(f"* {l}" for l in ranked_lines)
            return {
                "answer": f"{leader_line}\n\nFull ranking:\n{ranking_str}",
                "query_intent": intent,
                "sources": [
                    {
                        "user": c["user"],
                        "email": c["email"],
                        "filename": c["filename"],
                        "document_type": c.get("document_type", ""),
                        "doc_category": c.get("doc_category", ""),
                        "relevance": c["relevance_score"],
                        "uploaded_at": c["uploaded_at"],
                    }
                    for c in chunks[:5]
                ],
            }

    # Pre-compute category counts for category/grouping AGGREGATE queries
    category_summary = ""
    if intent == "AGGREGATE" and any(
        w in query.lower() for w in ["category", "categories", "type", "group",
                                      "breakdown", "distribution", "group by"]
    ):
        from collections import Counter
        cat_counts: Counter = Counter()
        for c in chunks:
            raw_cat = _extract_from_structured_line(c["text"], "Category").strip()
            if raw_cat:
                # Normalise: "CUAS/SDR" → "CUAS", "CUAS/COMINT" → "CUAS"
                normalised = raw_cat.split("/")[0].strip()
                cat_counts[normalised] += 1
        if cat_counts:
            category_summary = (
                "\nPRE-COMPUTED CATEGORY COUNTS (normalised, authoritative):\n"
                + "\n".join(
                    f"  {cat}: {count} projects"
                    for cat, count in cat_counts.most_common()
                )
                + f"\nCategory with most projects: "
                  f"{cat_counts.most_common(1)[0][0]} "
                  f"({cat_counts.most_common(1)[0][1]} projects).\n"
                  "Your answer must use these exact counts.\n"
            )

    # Step 5: build context string
    context_parts = []
    if intent == "STATUS" and status_value is not None:
        # Pre-filtered STATUS — tell the LLM chunks are already filtered and
        # present only the fields it needs (Project, Status, People, File).
        for i, chunk in enumerate(chunks):
            proj    = _extract_from_structured_line(chunk["text"], "Project") or "(unknown)"
            status  = _extract_from_structured_line(chunk["text"], "Status")  or "(unknown)"
            people_ = _extract_from_structured_line(chunk["text"], "People involved") or _extract_from_structured_line(chunk["text"], "People")
            context_parts.append(
                f"[Source {i+1}] Project: {proj} | Status: {status} | "
                f"People: {people_} | File: {chunk['filename']}"
            )
    elif intent == "TEMPORAL":
        # FIX 5: Exclude Author field for TEMPORAL queries — Author is the file
        # uploader (e.g. Pratyush uploaded Page0 file) not the project person.
        # Showing Author causes LLM to attribute projects to the uploader.
        for i, chunk in enumerate(chunks):
            context_parts.append(
                f"[Source {i+1}] File: {chunk['filename']}\n"
                f"{chunk['text']}"
            )
    else:
        for i, chunk in enumerate(chunks):
            date_str = chunk["uploaded_at"][:10] if chunk.get("uploaded_at") else "unknown"
            doc_type = chunk.get("document_type", "")
            doc_cat  = chunk.get("doc_category", "")
            type_part = f" | Format: {doc_type}" if doc_type else ""
            cat_part  = f" | Category: {doc_cat.replace('_', ' ').title()}" if doc_cat else ""
            context_parts.append(
                f"[Source {i+1}] Author: {chunk['user']} ({chunk['email']}){type_part}{cat_part} | "
                f"File: {chunk['filename']} | Uploaded: {date_str} | Relevance: {chunk['relevance_score']}\n"
                f"{chunk['text']}"
            )
    context_str = "\n\n---\n\n".join(context_parts)

    # Build file inventory for cross-document context
    seen_files: dict = {}
    for c in chunks:
        key = c["filename"]
        if key not in seen_files:
            seen_files[key] = f"{c['user']} ({c.get('doc_category', '').replace('_', ' ')})"
    files_summary = "\n".join(
        f"  • {fname} — by {info}" for fname, info in seen_files.items()
    )

    people_in_context = list({c['user'] for c in chunks if c['user'] != 'Unknown'})
    people_str = ", ".join(people_in_context) if people_in_context else "none"

    # Step 6: build prompt and call LLM
    system = _build_system_prompt(intent)
    if intent == "STATUS" and status_value is not None:
        system += (
            f"\n\nAll source chunks below have been PRE-FILTERED to only include rows where "
            f"Status = '{status_value}'. Your job is ONLY to extract the Project name "
            f"from each chunk and list them. Do not re-evaluate the status."
        )
    # For general STATUS queries (no specific status in query), instruct the LLM
    # to group by the exact Status field value rather than inferring it.
    if intent == "STATUS" and status_value is None:
        system += (
            "\n\nSince no specific status was requested, group your answer by status value. "
            "For each chunk, read the exact text after 'Status:' up to the next '|' character. "
            "Group all items under their exact status label. Do not infer or paraphrase status."
        )
    prompt = f"""DOCUMENTS IN CONTEXT ({len(seen_files)} file(s)):
{files_summary}
{negation_precomputed}{intersection_precomputed}{category_precomputed}{people_count_precomputed}{most_projects_precomputed}{count_note}{category_summary}
PEOPLE PRESENT IN SOURCES (ONLY these people exist in the knowledge base): {people_str}

SOURCE CHUNKS:
{context_str}

USER QUESTION: {query}

Instructions:
- Answer using ONLY the sources above.
- Follow the intent-specific instruction in the system prompt exactly.
- Cite every sentence with [Source N].
- If someone or something is not in the sources, say so directly — do not guess."""

    answer = _strip_hallucinated_tail(_call_ollama(prompt, system))

    return {
        "answer": answer,
        "query_intent": intent,
        "sources": [
            {
                "user": c["user"],
                "email": c["email"],
                "filename": c["filename"],
                "document_type": c.get("document_type", ""),
                "doc_category": c.get("doc_category", ""),
                "relevance": c["relevance_score"],
                "uploaded_at": c["uploaded_at"],
            }
            for c in chunks
        ],
    }
