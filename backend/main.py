from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from backend.config import CORS_ORIGINS
from backend.routers import auth_router, upload_router, query_router, projects_router

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Constelli RAG System", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router.router)
app.include_router(upload_router.router)
app.include_router(query_router.router)
app.include_router(projects_router.router)

@app.get("/health")
def health():
    return {"status": "ok", "system": "Constelli RAG"}