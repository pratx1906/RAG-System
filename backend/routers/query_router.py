from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from jose import jwt, JWTError
from backend.config import SECRET_KEY, ALGORITHM
from backend.rag.llm_chain import answer_query
from backend.logger import get_logger

router = APIRouter(prefix="/query", tags=["Query"])
log = get_logger("audit.query")

class QueryRequest(BaseModel):
    question: str

def get_current_user(authorization: str = Header(...)):
    try:
        token = authorization.split(" ", 1)[-1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"email": payload["sub"], "name": payload["name"]}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

@router.post("/")
def query(req: QueryRequest, current_user: dict = Depends(get_current_user)):
    result = answer_query(req.question, user_email=current_user["email"])
    log.info("query_answered", extra={"event": "query_answered", "email": current_user["email"], "question_preview": req.question[:120], "sources_returned": len(result.get("sources", []))})
    return result