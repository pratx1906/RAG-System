import os, uuid, aiofiles
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from datetime import datetime
from jose import jwt, JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.config import UPLOAD_DIR, SECRET_KEY, ALGORITHM, UPLOAD_MAX_MB
from backend.db.models import get_db, UploadRecord
from backend.db.chroma_client import get_documents_collection
from backend.ingestion.document_parser import parse_document, SUPPORTED_EXTENSIONS
from backend.ingestion.chunker import chunk_text
from backend.ingestion.embedder import embed_texts
from backend.logger import get_logger
from pathlib import Path

router = APIRouter(prefix="/upload", tags=["Upload"])
limiter = Limiter(key_func=get_remote_address)
log = get_logger("audit.upload")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Uniform 120-word chunks across all categories for consistent, precise
# semantic matching. Small overlap avoids context bleed that causes hallucination.
CHUNK_CONFIGS = {
    "project_resources": {"chunk_size": 120, "overlap": 15},
    "personal_schedule":  {"chunk_size": 120, "overlap": 15},
    "academic_paper":     {"chunk_size": 120, "overlap": 15},
}
VALID_CATEGORIES = set(CHUNK_CONFIGS.keys())

def get_current_user(authorization: str = Header(...)):
    try:
        token = authorization.split(" ", 1)[-1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"email": payload["sub"], "name": payload["name"], "uid": payload["uid"]}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

@router.post("/")
@limiter.limit("30/minute")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    doc_category: str = Form("project_resources"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    ip = get_remote_address(request)
    if doc_category not in VALID_CATEGORIES:
        doc_category = "project_resources"
    chunk_cfg = CHUNK_CONFIGS[doc_category]

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        log.warning("upload_rejected", extra={"event": "upload_rejected", "email": current_user["email"], "upload_filename": file.filename, "reason": "unsupported_type", "ext": ext, "ip": ip})
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    content = await file.read()
    if len(content) > UPLOAD_MAX_MB * 1024 * 1024:
        log.warning("upload_rejected", extra={"event": "upload_rejected", "email": current_user["email"], "upload_filename": file.filename, "reason": "file_too_large", "size_bytes": len(content), "ip": ip})
        raise HTTPException(status_code=413, detail=f"File exceeds maximum size of {UPLOAD_MAX_MB}MB")

    # Save file
    file_id = str(uuid.uuid4())
    save_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    # Parse & chunk
    try:
        text = parse_document(save_path)
    except Exception as e:
        os.remove(save_path)
        log.error("upload_parse_failed", extra={"event": "upload_parse_failed", "email": current_user["email"], "upload_filename": file.filename, "error": str(e), "ip": ip})
        raise HTTPException(status_code=422, detail=f"Could not parse file: {str(e)}")

    chunks = chunk_text(text, chunk_size=chunk_cfg["chunk_size"], overlap=chunk_cfg["overlap"])
    if not chunks:
        raise HTTPException(status_code=422, detail="Document appears to be empty or unreadable.")

    # Embed & store in ChromaDB
    uploaded_at = datetime.utcnow().isoformat()
    document_type = ext.lstrip(".").upper()
    embeddings = embed_texts(chunks)
    collection = get_documents_collection()
    chunk_ids = [f"{file_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "user_email":    current_user["email"],
            "user_name":     current_user["name"],
            "user_id":       current_user["uid"],
            "filename":      file.filename,
            "file_id":       file_id,
            "document_type": document_type,
            "doc_category":  doc_category,
            "chunk_size":    chunk_cfg["chunk_size"],
            "uploaded_at":   uploaded_at,
            "chunk_index":   i,
            "total_chunks":  len(chunks),
        }
        for i in range(len(chunks))
    ]
    collection.add(ids=chunk_ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)

    # Save upload record to SQLite
    record = UploadRecord(
        user_id=current_user["uid"],
        filename=file.filename,
        file_type=ext,
        chunk_count=len(chunks)
    )
    db.add(record)
    db.commit()

    log.info("upload_success", extra={"event": "upload_success", "email": current_user["email"], "user_id": current_user["uid"], "upload_filename": file.filename, "document_type": document_type, "doc_category": doc_category, "chunk_size": chunk_cfg["chunk_size"], "size_bytes": len(content), "chunks": len(chunks), "file_id": file_id, "ip": ip})
    return {"message": "File uploaded and indexed successfully", "chunks": len(chunks), "upload_filename": file.filename}