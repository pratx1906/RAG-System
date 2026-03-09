import chromadb
from chromadb.config import Settings
from backend.config import CHROMA_PERSIST_DIR

_client = None

def get_chroma_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
    return _client

def get_documents_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="company_documents",
        metadata={"hnsw:space": "cosine"}
    )

def get_projects_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="project_summaries",
        metadata={"hnsw:space": "cosine"}
    )