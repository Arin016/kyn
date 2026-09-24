#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-${KYN_PORT:-8765}}"
HOST="${KYN_HOST:-127.0.0.1}"

command -v uv >/dev/null || { echo "Install uv: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
command -v npm >/dev/null || { echo "Install Node.js/npm first." >&2; exit 1; }

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

uv sync --extra server

if [[ ! -d web-ui/node_modules ]]; then
  npm --prefix web-ui ci
fi
npm --prefix web-ui run build

echo ""
echo "Starting Ari at http://$HOST:$PORT/ (Ctrl+C to stop)"
exec uv run ari serve --host "$HOST" --port "$PORT"
