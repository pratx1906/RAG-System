import logging
from typing import List

ROW_SEPARATOR = "\n---\n"

_log = logging.getLogger("chunker")


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """
    Router: detects tabular data (rows separated by \\n---\\n from structured parsers)
    vs prose text.
    - Tabular: each row becomes its own chunk, no overlap needed.
    - Prose: original word-based sliding-window chunking.
    """
    separator_found = ROW_SEPARATOR in text
    _log.debug(
        "[chunk_text] separator_detected=%s | first_200_chars=%r",
        separator_found,
        text[:200],
    )
    if separator_found:
        return _chunk_tabular(text)
    return _chunk_prose(text, chunk_size, overlap)


def _chunk_tabular(text: str) -> List[str]:
    """One chunk per spreadsheet/CSV row. Minimum 20 chars to filter empty rows."""
    rows = text.split(ROW_SEPARATOR)
    return [r.strip() for r in rows if len(r.strip()) > 20]


def _chunk_prose(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Word-based sliding-window chunking for prose documents."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i: i + chunk_size]
        chunks.append(" ".join(chunk))
        i += chunk_size - overlap
    return [c for c in chunks if len(c.strip()) > 50]
