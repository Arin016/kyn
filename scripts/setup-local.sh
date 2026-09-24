#!/usr/bin/env bash
# Ari one-command local setup. Run from anywhere inside the checkout:
#   bash scripts/setup-local.sh
# It installs missing tools (uv, Node.js), installs all dependencies,
# builds the web UI, frees the serve port, and starts the control room.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-${KYN_PORT:-8765}}"
HOST="${KYN_HOST:-127.0.0.1}"

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then return 0; fi
  echo "uv not found — installing with the official installer..."
  command -v curl >/dev/null || { echo "curl is required to install uv." >&2; exit 1; }
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null || {
    echo "uv installed but not on PATH. Add ~/.local/bin to PATH and re-run." >&2
    exit 1
  }
}

ensure_node() {
  if command -v npm >/dev/null 2>&1; then return 0; fi
  echo "Node.js/npm not found — attempting automatic install..."
  if command -v brew >/dev/null 2>&1; then
    brew install node
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y nodejs npm
  else
    echo "Could not install Node.js automatically." >&2
    echo "Install Node.js LTS from https://nodejs.org/ then re-run this script." >&2
    exit 1
  fi
  command -v npm >/dev/null || {
    echo "Node.js install did not provide npm. Install it manually, then re-run." >&2
    exit 1
  }
}

ensure_uv
ensure_node

# Free the serve port (listeners only — never kills browsers/clients).
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti:"$PORT" -sTCP:LISTEN || true)"
  if [[ -n "$PIDS" ]]; then
    echo "Port $PORT in use by listener: $PIDS — stopping it."
    # shellcheck disable=SC2086
    kill -9 $PIDS
    sleep 1
  fi
else
  echo "lsof not found, skipping port check for $PORT." >&2
fi

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example (edit tokens as needed)."
fi

echo "Installing Python dependencies..."
uv sync --extra server

echo "Installing UI dependencies..."
if [[ ! -d web-ui/node_modules ]]; then
  npm --prefix web-ui ci
else
  npm --prefix web-ui install --no-audit --no-fund
fi

echo "Building UI..."
npm --prefix web-ui run build

echo ""
echo "Starting Ari at http://$HOST:$PORT/ (Ctrl+C to stop)"
exec uv run ari serve --host "$HOST" --port "$PORT"
