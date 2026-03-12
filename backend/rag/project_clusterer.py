"""
Project lister: reads all chunks directly from ChromaDB and extracts project
info from the stored structured text. No ML clustering, no LLM calls.

Extracts per-project:
  - project name  (from "Project: ..." fields or "X is working on Y" sentences)
  - people        (from "People Involved: ..." fields + uploader metadata)
  - status        (from "Status: ..." fields)
  - source files  (from chunk metadata)
  - chunk count   (how many chunks mention this project)
"""

import re
from collections import defaultdict
from datetime import datetime, timezone

from backend.db.chroma_client import get_documents_collection

# ── Extraction patterns ───────────────────────────────────────────────────────

_RE_PROJECT = re.compile(
    r'\bProject:\s*([^|\n\r]+?)(?:\s*\||$)', re.IGNORECASE
)
_RE_PEOPLE = re.compile(
    r'\b(?:People\s+Involved|Assigned\s+To|Owner|Team|Members|People):\s*([^|\n\r]+?)(?:\s*\||$)',
    re.IGNORECASE,
)
_RE_STATUS = re.compile(r'\bStatus:\s*([^,)|\n\r]+)', re.IGNORECASE)
_RE_WORKING = re.compile(
    r'^(.+?)\s+(?:is|are)\s+working\s+on\s+(.+?)(?:\s*[\(\.,]|$)',
    re.MULTILINE,
)

_IGNORE_VALUES = {"none", "n/a", "-", "", "nan"}


def _split_people(raw: str):
    return [
        p.strip()
        for p in re.split(r"[,;]", raw)
        if p.strip().lower() not in _IGNORE_VALUES
    ]


def _extract_fields(text: str):
    """Return (project_name, people_list, status) extracted from one chunk."""
    project_name = None
    people: list = []
    status = None

    m = _RE_PROJECT.search(text)
    if m:
        project_name = m.group(1).strip().strip(".")

    m = _RE_PEOPLE.search(text)
    if m:
        people = _split_people(m.group(1))

    m = _RE_STATUS.search(text)
    if m:
        status = m.group(1).strip().strip(".")

    # Fallback: "Alice is working on X"
    if not project_name:
        wm = _RE_WORKING.search(text)
        if wm:
            project_name = wm.group(2).strip().strip(".")
            if not people:
                people = _split_people(wm.group(1))

    return project_name, people, status


# ── Public API ────────────────────────────────────────────────────────────────

def list_all_projects():
    """
    Scan all project_resources and personal_schedule chunks in ChromaDB
    and return a deduplicated list of projects with people and status.

    Returns list of dicts:
      id, project_name, status, people, sources, doc_categories, chunk_count,
      refreshed_at
    """
    collection = get_documents_collection()
    try:
        all_data = collection.get(
            include=["documents", "metadatas"],
            where={"doc_category": {"$eq": "personal_schedule"}},
        )
    except Exception:
        # Empty collection or unsupported where clause — fetch everything
        all_data = collection.get(include=["documents", "metadatas"])

    if not all_data or not all_data.get("ids"):
        return []

    # key: lowercased project name → aggregator
    agg_map: dict = defaultdict(lambda: {
        "project_name": "",
        "status": None,
        "people": set(),
        "sources": set(),
        "doc_categories": set(),
        "chunk_count": 0,
    })

    for doc, meta in zip(all_data["documents"], all_data["metadatas"]):
        project_name, people, status = _extract_fields(doc)
        if not project_name:
            continue

        key = project_name.lower().strip()
        agg = agg_map[key]

        if not agg["project_name"]:
            agg["project_name"] = project_name

        if status and not agg["status"]:
            agg["status"] = status

        agg["people"].update(people)

        if meta:
            if meta.get("user_name"):
                agg["people"].add(meta["user_name"])
            if meta.get("filename"):
                agg["sources"].add(meta["filename"])
            if meta.get("doc_category"):
                agg["doc_categories"].add(meta["doc_category"])

        agg["chunk_count"] += 1

    refreshed_at = datetime.now(timezone.utc).isoformat()

    return [
        {
            "id": key,
            "project_name": agg["project_name"],
            "status": agg["status"] or "Unknown",
            "people": sorted(agg["people"]),
            "sources": sorted(agg["sources"]),
            "doc_categories": sorted(agg["doc_categories"]),
            "chunk_count": agg["chunk_count"],
            "refreshed_at": refreshed_at,
        }
        for key, agg in sorted(
            agg_map.items(),
            key=lambda kv: kv[1]["chunk_count"],
            reverse=True,
        )
    ]


# Keep old name as alias so any existing import still works
def run_project_clustering():
    return list_all_projects()
