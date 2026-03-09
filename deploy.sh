#!/usr/bin/env bash
# ---------------------------------------------------------------
# Constelli RAG — Server Deployment Script
# Starts the backend API + Ollama on this machine.
# The frontend is deployed separately on Vercel/Netlify.
#
# Usage: bash deploy.sh
# ---------------------------------------------------------------
set -euo pipefail

echo "==> Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker is not installed." >&2
    exit 1
fi

if [ ! -f .env ]; then
    echo "ERROR: .env file not found."
    echo "       Copy .env.example to .env and fill in your values first."
    echo "       Generate SECRET_KEY with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi

# Verify SECRET_KEY is set and not a placeholder
SECRET_KEY_VAL=$(grep -E '^SECRET_KEY=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")
if [ -z "$SECRET_KEY_VAL" ] || [ "$SECRET_KEY_VAL" = "REPLACE_WITH_GENERATED_SECRET" ]; then
    echo "ERROR: SECRET_KEY is not set in .env."
    echo "       Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi

# Verify CORS_ORIGINS points to the frontend domain
CORS_VAL=$(grep -E '^CORS_ORIGINS=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" || echo "")
if [ -z "$CORS_VAL" ] || echo "$CORS_VAL" | grep -q "your-app.vercel.app"; then
    echo "WARNING: CORS_ORIGINS in .env still has the placeholder value."
    echo "         Set it to your actual Vercel/Netlify URL before your frontend can call this API."
fi

echo "==> Building backend image and starting services..."
docker compose up -d --build --remove-orphans

echo ""
echo "==> Service status:"
docker compose ps

echo ""
echo "==> Backend API is starting on port 8000."
echo "    - Health check: http://localhost:8000/health"
echo "    - API docs:     http://localhost:8000/docs"
echo ""
echo "    Ollama models are being pulled in the background."
echo "    Monitor with: docker compose logs -f ollama-init"
echo "    All logs:     docker compose logs -f"
echo ""
echo "    Set VITE_API_URL=http://<your-public-ip>:8000 in your Vercel/Netlify environment."
