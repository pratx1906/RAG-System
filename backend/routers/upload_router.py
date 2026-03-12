import os, uuid, aiofiles
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Header, Request, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime
from jose import jwt, JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.config import UPLOAD_DIR, SECRET_KEY, ALGORITHM, UPLOAD_MAX_MB
from backend.db.models import get_db, UploadRecord, SessionLocal
from backend.db.chroma_client import get_documents_collection
from backend.ingestion.document_parser import parse_document, SUPPORTED_EXTENSIONS
from backend.ingestion.chunker import chunk_text, chunk_hash as compute_chunk_hash
from backend.ingestion.embedder import embed_texts, MIN_SUCCESS_RATE
from backend.logger import get_logger
from pathlib import Path

router = APIRouter(prefix="/upload", tags=["Upload"])
limiter = Limiter(key_func=get_remote_address)
log = get_logger("audit.upload")
os.makedirs(UPLOAD_DIR, exist_ok=True)

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


def _process_document_background(
    save_path: str, file_id: str, ext: str,
    original_filename: str, doc_category: str,
    chunk_cfg: dict, current_user: dict,
    uploaded_at: str, ip: str, content_size: int
):
    """Parse, embed and store a document — runs in background after upload returns."""
    db = SessionLocal()
    try:
        text = parse_document(save_path)
        chunks = chunk_text(text, chunk_size=chunk_cfg["chunk_size"], overlap=chunk_cfg["overlap"])
        if not chunks:
            log.warning("upload_empty_document", extra={
                "event": "upload_empty_document",
                "email": current_user["email"],
                "upload_filename": original_filename,
                "ip": ip,
            })
            return

        document_type = ext.lstrip(".").upper()

        # ── Cross-run deduplication ───────────────────────────────────────────
        # Compute a hash for every chunk and query ChromaDB for any that already
        # exist (from a previous upload of the same file).  Only embed and store
        # chunks that are genuinely new.
        all_hashes = [compute_chunk_hash(c) for c in chunks]

        collection = get_documents_collection()
        try:
            existing = collection.get(
                where={"chunk_hash": {"$in": all_hashes}},
                include=[],   # we only need IDs; embeddings/documents not required
            )
            existing_hashes = set()
            if existing and existing.get("metadatas"):
                for meta in existing["metadatas"]:
                    if meta and meta.get("chunk_hash"):
                        existing_hashes.add(meta["chunk_hash"])
        except Exception as exc:
            # If the query fails (e.g. empty collection), treat all chunks as new
            log.warning(
                "upload_dedup_query_failed",
                extra={"event": "upload_dedup_query_failed", "error": str(exc), "ip": ip},
            )
            existing_hashes = set()

        new_indices = [i for i, h in enumerate(all_hashes) if h not in existing_hashes]
        n_skipped   = len(chunks) - len(new_indices)

        if n_skipped:
            log.info("upload_chunks_deduplicated", extra={
                "event": "upload_chunks_deduplicated",
                "email": current_user["email"],
                "upload_filename": original_filename,
                "skipped": n_skipped,
                "remaining": len(new_indices),
                "ip": ip,
            })

        if not new_indices:
            log.info("upload_all_chunks_exist", extra={
                "event": "upload_all_chunks_exist",
                "email": current_user["email"],
                "upload_filename": original_filename,
                "total_chunks": len(chunks),
                "ip": ip,
            })
            return

        new_chunks  = [chunks[i] for i in new_indices]
        new_hashes  = [all_hashes[i] for i in new_indices]

        # ── Embedding ─────────────────────────────────────────────────────────
        # embed_texts raises RuntimeError if success rate < MIN_SUCCESS_RATE
        try:
            raw_embeddings = embed_texts(new_chunks)
        except RuntimeError as exc:
            log.error("upload_embed_rate_too_low", extra={
                "event": "upload_embed_rate_too_low",
                "email": current_user["email"],
                "upload_filename": original_filename,
                "error": str(exc),
                "ip": ip,
            })
            return

        # Filter out chunks where embedding permanently failed (None = no zero-vector fallback)
        valid = [
            (new_chunks[i], raw_embeddings[i], new_indices[i], new_hashes[i])
            for i in range(len(new_chunks))
            if raw_embeddings[i] is not None
        ]
        if not valid:
            log.error("upload_all_embeddings_failed", extra={
                "event": "upload_all_embeddings_failed",
                "email": current_user["email"],
                "upload_filename": original_filename,
                "total_chunks": len(chunks),
                "ip": ip,
            })
            return

        valid_chunks, valid_embeddings, valid_indices, valid_hashes = zip(*valid)
        n_stored  = len(valid_chunks)
        n_failed  = len(new_chunks) - n_stored
        if n_failed:
            log.warning("upload_partial_embeddings", extra={
                "event": "upload_partial_embeddings",
                "email": current_user["email"],
                "upload_filename": original_filename,
                "stored": n_stored,
                "failed": n_failed,
                "ip": ip,
            })

        chunk_ids = [f"{file_id}_chunk_{i}" for i in valid_indices]
        metadatas = [
            {
                "user_email":    current_user["email"],
                "user_name":     current_user["name"],
                "user_id":       current_user["uid"],
                "filename":      original_filename,
                "file_id":       file_id,
                "document_type": document_type,
                "doc_category":  doc_category,
                "chunk_size":    chunk_cfg["chunk_size"],
                "uploaded_at":   uploaded_at,
                "chunk_index":   i,
                "total_chunks":  n_stored,
                "chunk_hash":    h,
            }
            for i, h in zip(valid_indices, valid_hashes)
        ]
        collection.add(
            ids=chunk_ids,
            embeddings=list(valid_embeddings),
            documents=list(valid_chunks),
            metadatas=metadatas,
        )

        record = UploadRecord(
            user_id=current_user["uid"],
            filename=original_filename,
            file_type=ext,
            chunk_count=n_stored,
        )
        db.add(record)
        db.commit()

        log.info("upload_success", extra={
            "event": "upload_success",
            "email": current_user["email"],
            "user_id": current_user["uid"],
            "upload_filename": original_filename,
            "document_type": document_type,
            "doc_category": doc_category,
            "chunk_size": chunk_cfg["chunk_size"],
            "size_bytes": content_size,
            "chunks_stored": n_stored,
            "chunks_skipped": n_skipped,
            "file_id": file_id,
            "ip": ip,
        })

    except Exception as e:
        if os.path.exists(save_path):
            os.remove(save_path)
        log.error("upload_process_failed", extra={
            "event": "upload_process_failed",
            "email": current_user["email"],
            "upload_filename": original_filename,
            "error": str(e),
            "ip": ip,
        })
    finally:
        db.close()


@router.post("/")
@limiter.limit("30/minute")
async def upload_file(
    request: Request,
    background_tasks: BackgroundTasks,
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

    # Save file immediately
    file_id = str(uuid.uuid4())
    save_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    uploaded_at = datetime.utcnow().isoformat()

    # Schedule heavy processing (parse + embed + store) in background
    background_tasks.add_task(
        _process_document_background,
        save_path, file_id, ext,
        file.filename, doc_category,
        chunk_cfg, current_user,
        uploaded_at, ip, len(content),
    )

    log.info("upload_received", extra={
        "event": "upload_received",
        "email": current_user["email"],
        "upload_filename": file.filename,
        "size_bytes": len(content),
        "file_id": file_id,
        "ip": ip,
    })
    return {"message": "File received and is being processed", "filename": file.filename, "file_id": file_id}
