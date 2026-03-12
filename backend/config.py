from dotenv import load_dotenv
import os

load_dotenv()

ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "constelli.com")
SECRET_KEY = os.getenv("SECRET_KEY", "")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 480))
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chromadb")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./data/uploads")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/constelli.db")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
UPLOAD_MAX_MB = int(os.getenv("UPLOAD_MAX_MB", 20))
ORG_SHARED_PASSWORD = os.getenv("ORG_SHARED_PASSWORD", "")

_WEAK_KEYS = {"", "supersecret", "change_this_to_a_long_random_string_in_production"}
if not SECRET_KEY or SECRET_KEY in _WEAK_KEYS or "change_this" in SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "SECRET_KEY is not set or is insecure. "
        "Set a strong random value (32+ chars) in your .env file."
    )