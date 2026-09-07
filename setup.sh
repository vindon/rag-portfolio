#!/usr/bin/env bash
# =============================================================================
# RAG Portfolio — macOS ARM64 (Apple Silicon) Setup Script
# Tested on MacBook Pro M1/M2/M3/M4/M5
# =============================================================================
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[setup]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }

log "RAG Portfolio setup starting..."
echo ""

# ── Check Homebrew ────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  err "Homebrew not found. Install it first: https://brew.sh"
fi
log "Homebrew ✓"

# ── Python 3.11+ ─────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  log "Installing Python 3.11 via Homebrew..."
  brew install python@3.11
fi
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log "Python $PYTHON_VERSION ✓"

# ── Ollama ────────────────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  log "Installing Ollama..."
  brew install ollama
fi
log "Ollama ✓"

# ── Pull required Ollama models ───────────────────────────────────────────────
log "Pulling nomic-embed-text (embedding model)..."
ollama pull nomic-embed-text

warn "Ollama LLM model: if you set LLM_PROVIDER=ollama, run: ollama pull llama3.2"
echo ""

# ── Virtual environment ───────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  log "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
log "Virtual environment activated ✓"

# ── Upgrade pip ───────────────────────────────────────────────────────────────
pip install --upgrade pip --quiet

# ── Install all project dependencies ─────────────────────────────────────────
PROJECTS=(
  "01-hr-policy-rag"
  "02-contract-review-chat"
  "03-marketing-content-hub"
  "04-techDocs-rag-pipeline"
  "05-it-helpdesk-agent"
)

for project in "${PROJECTS[@]}"; do
  log "Installing $project dependencies..."
  pip install -r "$project/requirements.txt" --quiet
done

# ── Copy .env ─────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  cp .env.example .env
  warn ".env created from .env.example — add your GROQ_API_KEY before running"
fi

# ── Start Ollama service ──────────────────────────────────────────────────────
log "Starting Ollama service in background..."
ollama serve &>/dev/null &
sleep 2
log "Ollama service started ✓"

echo ""
echo "════════════════════════════════════════════════════════════"
log "Setup complete! Next steps:"
echo ""
echo "  1. Add your GROQ_API_KEY to .env"
echo "     Get free key: https://console.groq.com"
echo ""
echo "  2. Activate the virtual environment:"
echo "     source .venv/bin/activate"
echo ""
echo "  3. Run any project:"
echo "     cd 01-hr-policy-rag && python main.py"
echo "     cd 02-contract-review-chat && streamlit run app.py"
echo "     cd 03-marketing-content-hub && streamlit run app.py"
echo "     cd 04-techDocs-rag-pipeline && streamlit run app.py"
echo "     cd 05-it-helpdesk-agent && streamlit run app.py"
echo ""
echo "  4. (Optional) Docker for persistent vector DBs:"
echo "     docker compose up qdrant milvus weaviate"
echo "════════════════════════════════════════════════════════════"
