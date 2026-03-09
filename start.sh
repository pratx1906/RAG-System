#!/bin/bash
echo "🔭 Starting Constelli RAG System..."

# Pull required Ollama models
ollama pull gemma3:4b
ollama pull nomic-embed-text

# Create data dirs
mkdir -p data/chromadb data/uploads

# Activate Python virtual environment
source venv/Scripts/activate

# Start backend
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start frontend
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo "✅ Backend running at http://localhost:8000"
echo "✅ Frontend running at http://localhost:5173"
echo "Press Ctrl+C to stop both."
wait $BACKEND_PID $FRONTEND_PID
