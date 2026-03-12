from fastapi import APIRouter, Depends, Header, HTTPException, Request
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.config import SECRET_KEY, ALGORITHM
from backend.db.models import get_db, UploadRecord, User
from backend.rag.project_clusterer import list_all_projects
from backend.logger import get_logger

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
def list_projects(current_user: dict = Depends(get_current_user)):
    """Return all projects extracted directly from uploaded documents."""
    projects = list_all_projects()
    log.info("projects_listed", extra={
        "event": "projects_listed",
        "email": current_user["email"],
        "count": len(projects),
    })
    return projects

@router.post("/recluster")
def recluster(request: Request, current_user: dict = Depends(get_current_user)):
    """No-op kept for backwards compatibility with Upload.jsx. Returns live project list."""
    ip = get_remote_address(request)
    projects = list_all_projects()
    log.info("projects_refreshed", extra={
        "event": "projects_refreshed",
        "email": current_user["email"],
        "projects_count": len(projects),
        "ip": ip,
    })
    return {"message": f"Found {len(projects)} projects", "projects": projects}

@router.get("/my-uploads")
def my_uploads(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    user = db.query(User).filter(User.email == current_user["email"]).first()
    if not user:
        return []
    uploads = db.query(UploadRecord).filter(UploadRecord.user_id == user.id).all()
    log.info("my_uploads_listed", extra={
        "event": "my_uploads_listed",
        "email": current_user["email"],
        "count": len(uploads),
    })
    return [
        {
            "filename": u.filename,
            "file_type": u.file_type,
            "uploaded_at": u.uploaded_at.isoformat(),
            "chunks": u.chunk_count,
        }
        for u in uploads
    ]
