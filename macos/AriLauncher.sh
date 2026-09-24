#!/bin/bash
set -u

APP_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SERVER="$APP_ROOT/Contents/Resources/AriServer"
PORT="${ARI_PORT:-${KYN_PORT:-8765}}"
URL="http://127.0.0.1:$PORT/app/?desktop=1#setup"

if ! /usr/bin/curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$HOME/.opencode/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  export KYN_HOST="127.0.0.1"
  export KYN_PORT="$PORT"
  export KYN_CONTROL_URL="http://127.0.0.1:$PORT"
  nohup "$SERVER" >/dev/null 2>&1 </dev/null &
  for _ in $(/usr/bin/jot 40 1); do
    if /usr/bin/curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      break
    fi
    /bin/sleep 0.5
  done
fi

/usr/bin/open "$URL"
