from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from jose import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from backend.auth.domain_check import enforce_domain
from backend.db.models import get_db, User
from backend.logger import get_logger

router = APIRouter(prefix="/auth", tags=["Auth"])
limiter = Limiter(key_func=get_remote_address)
log = get_logger("audit.auth")

class LoginRequest(BaseModel):
    email: str
    name: str

def create_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    ip = get_remote_address(request)
    try:
        enforce_domain(req.email)
    except HTTPException:
        log.warning("login_rejected", extra={"event": "login_rejected", "email": req.email, "ip": ip, "reason": "domain_not_allowed"})
        raise

    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    is_new = user is None
    if is_new:
        user = User(email=email, name=req.name.strip())
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_token({"sub": user.email, "name": user.name, "uid": user.id})
    log.info("login_success", extra={"event": "login_success", "email": user.email, "user_id": user.id, "ip": ip, "new_user": is_new})
    return {"access_token": token, "token_type": "bearer", "user": {"email": user.email, "name": user.name}}