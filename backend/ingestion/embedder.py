import ollama
from backend.config import OLLAMA_EMBED_MODEL

# nomic-embed-text supports 8192 tokens (~6000 chars).
# 4000 chars safely covers dual-representation Excel chunks.
MAX_EMBED_CHARS = 4000

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings using nomic-embed-text.
    Handles errors per-chunk — one bad chunk does not fail the whole batch.
    Falls back to zero vector on error so ingestion always completes.
    """
    embeddings = []
    for i, text in enumerate(texts):
        try:
            response = ollama.embeddings(
                model=OLLAMA_EMBED_MODEL,
                prompt=text[:MAX_EMBED_CHARS]
            )
            embeddings.append(response["embedding"])
        except Exception as e:
            print(f"[embed_texts] ERROR on chunk {i}: {e}")
            # nomic-embed-text output dimension is 768
            embeddings.append([0.0] * 768)
    return embeddings
