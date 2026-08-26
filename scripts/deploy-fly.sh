#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v fly >/dev/null 2>&1; then
  echo "Install Fly CLI: https://fly.io/docs/hands-on/install-flyctl/" >&2
  exit 1
fi

APP_NAME="${FLY_APP_NAME:-kyn}"
REGION="${FLY_REGION:-iad}"
VOLUME_NAME="${FLY_VOLUME_NAME:-kyn_data}"

echo "Deploying KYN to Fly app: ${APP_NAME}"

if ! fly apps list 2>/dev/null | grep -q "^${APP_NAME}[[:space:]]"; then
  echo "Creating Fly app ${APP_NAME}..."
  fly apps create "$APP_NAME"
fi

if ! fly volumes list -a "$APP_NAME" 2>/dev/null | grep -q "$VOLUME_NAME"; then
  echo "Creating volume ${VOLUME_NAME} in ${REGION}..."
  fly volumes create "$VOLUME_NAME" --region "$REGION" --size 1 -a "$APP_NAME" -y
fi

if ! fly secrets list -a "$APP_NAME" 2>/dev/null | grep -q "KYN_ACCESS_TOKEN"; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo "Setting KYN_ACCESS_TOKEN (save this for first login):"
  echo "  ${TOKEN}"
  fly secrets set "KYN_ACCESS_TOKEN=${TOKEN}" -a "$APP_NAME"
fi

fly deploy -a "$APP_NAME"

echo ""
echo "Open: https://${APP_NAME}.fly.dev/app/?token=<your-KYN_ACCESS_TOKEN>"
echo "Docs: docs/deploy.md"
