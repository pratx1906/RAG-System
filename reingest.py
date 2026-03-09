"""
Direct re-ingestion script — bypasses HTTP/auth.
Parses, chunks, embeds and stores both Excel files directly into ChromaDB.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))

from backend.ingestion.document_parser import parse_document
from backend.ingestion.chunker import chunk_text
from backend.ingestion.embedder import embed_texts
from backend.db.chroma_client import get_documents_collection
from datetime import datetime

FILES = [
    {
        "path": "./data/uploads/a6ff6df7-1622-4a6a-ac46-3958f6e52d53.xlsx",
        "filename": "page0_anoushka.xlsx",
        "file_id": "a6ff6df7-1622-4a6a-ac46-3958f6e52d53",
        "user_email": "anoushka@constelli.com",
        "user_name": "Anoushka",
        "user_id": "user_anoushka",
        "doc_category": "personal_schedule",
    },
    {
        "path": "./data/uploads/feadfdc2-d128-423f-ba99-a4ea5094e38a.xlsx",
        "filename": "Page0_project list 1.xlsx",
        "file_id": "feadfdc2-d128-423f-ba99-a4ea5094e38a",
        "user_email": "pratyush@constelli.com",
        "user_name": "Pratyush",
        "user_id": "user_pratyush",
        "doc_category": "personal_schedule",
    },
]

collection = get_documents_collection()

for f in FILES:
    print(f"\n{'='*60}")
    print(f"Ingesting: {f['filename']}")
    print('='*60)

    text = parse_document(f["path"])
    chunks = chunk_text(text, chunk_size=120, overlap=15)
    print(f"  Chunks produced: {len(chunks)}")

    uploaded_at = datetime.utcnow().isoformat()
    embeddings = embed_texts(chunks)

    chunk_ids = [f"{f['file_id']}_chunk_{i}" for i in range(len(chunks))]
    def _extract_category(chunk_text: str) -> str:
        """Extract Category field value from chunk text for metadata storage."""
        m = re.search(r'[Cc]ategory:\s*([^|]+)', chunk_text)
        if m:
            return m.group(1).strip()
        return ""

    metadatas = [
        {
            "user_email":    f["user_email"],
            "user_name":     f["user_name"],
            "user_id":       f["user_id"],
            "filename":      f["filename"],
            "file_id":       f["file_id"],
            "document_type": "XLSX",
            "doc_category":  f["doc_category"],
            "chunk_size":    120,
            "uploaded_at":   uploaded_at,
            "chunk_index":   i,
            "total_chunks":  len(chunks),
            "category":      _extract_category(chunks[i]),
        }
        for i in range(len(chunks))
    ]
    collection.add(ids=chunk_ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
    print(f"  Stored {len(chunks)} chunks in ChromaDB.")

print(f"\nTotal in ChromaDB: {collection.count()}")
