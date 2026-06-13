#!/usr/bin/env bash
# Jarvis one-command setup. Works on Linux/macOS (and WSL on Windows).
# Usage: ./bootstrap.sh [extras]   e.g.  ./bootstrap.sh all
set -euo pipefail

EXTRAS="${1:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "==> Jarvis bootstrap"

# 1. Python venv
if [ ! -d ".venv" ]; then
  echo "==> creating virtualenv (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip

# 2. Install package (+ optional extras)
if [ -n "$EXTRAS" ]; then
  echo "==> installing jarvis[$EXTRAS]"
  pip install --quiet -e ".[$EXTRAS]"
else
  echo "==> installing jarvis (core)"
  pip install --quiet -e .
fi
# MCP discovery is optional but recommended.
pip install --quiet mcp || echo "   (mcp SDK optional; skipped)"

# 3. .env
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "==> created .env (fill in API keys, or skip and use Ollama)"
fi

# 4. Ollama local fallback (so Jarvis works with zero API keys)
if command -v ollama >/dev/null 2>&1; then
  echo "==> Ollama found; ensuring a local model is available"
  if ! ollama list 2>/dev/null | grep -q "llama3.1"; then
    echo "   pulling llama3.1 (this can take a while)…"
    ollama pull llama3.1 || echo "   (pull failed; set an API key instead)"
  fi
else
  echo "==> Ollama not installed. Either install it (https://ollama.com) for a"
  echo "    zero-key local fallback, or put an API key in .env."
fi

# 5. Initialise DB + show capability report
echo "==> initialising and probing capabilities"
python -m jarvis doctor || true

echo ""
echo "==> Done. Start Jarvis with:"
echo "    source .venv/bin/activate && jarvis chat"
