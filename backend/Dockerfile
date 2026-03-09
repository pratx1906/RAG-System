FROM python:3.11-slim

WORKDIR /app

# System deps needed by chromadb, sentence-transformers, and document parsers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1001 appuser

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and set ownership
COPY --chown=appuser:appuser . .

# Create data directories with correct ownership (volume will mount here)
RUN mkdir -p /app/data/chromadb /app/data/uploads \
    && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
