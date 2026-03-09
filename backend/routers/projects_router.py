from fastapi import APIRouter, Depends, Header, HTTPException, Request
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.config import SECRET_KEY, ALGORITHM
from backend.db.models import get_db, ProjectCluster, UploadRecord, User
from backend.rag.project_clusterer import run_project_clustering
from backend.logger import get_logger
import json

router = APIRouter(prefix="/projects", tags=["Projects"])
log = get_logger("audit.projects")

def get_current_user(authorization: str = Header(...)):
    try:
        token = authorization.split(" ", 1)[-1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"email": payload["sub"], "name": payload["name"]}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

@router.get("/")
def list_projects(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    clusters = db.query(ProjectCluster).all()
    log.info("projects_listed", extra={"event": "projects_listed", "email": current_user["email"], "count": len(clusters)})
    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "keywords": json.loads(c.keywords or "[]"),
            "members": json.loads(c.member_emails or "[]"),
            "updated_at": c.updated_at.isoformat()
        }
        for c in clusters
    ]

@router.post("/recluster")
def recluster(request: Request, current_user: dict = Depends(get_current_user)):
    """Trigger re-clustering of all documents. Can be called anytime after new uploads."""
    ip = get_remote_address(request)
    log.info("recluster_triggered", extra={"event": "recluster_triggered", "email": current_user["email"], "ip": ip})
    results = run_project_clustering()
    log.info("recluster_completed", extra={"event": "recluster_completed", "email": current_user["email"], "projects_count": len(results), "ip": ip})
    return {"message": f"Clustered into {len(results)} projects", "projects": results}

@router.get("/my-uploads")
def my_uploads(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    user = db.query(User).filter(User.email == current_user["email"]).first()
    if not user:
        return []
    uploads = db.query(UploadRecord).filter(UploadRecord.user_id == user.id).all()
    log.info("my_uploads_listed", extra={"event": "my_uploads_listed", "email": current_user["email"], "count": len(uploads)})
    return [
        {
            "filename": u.filename,
            "file_type": u.file_type,
            "uploaded_at": u.uploaded_at.isoformat(),
            "chunks": u.chunk_count,
            "project": u.inferred_project
        }
        for u in uploads
    ]