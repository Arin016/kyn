#!/usr/bin/env bash
# Build ari-crew wheels/sdists for PyPI. The wheel bundles the built web UI,
# so Rosa from PyPI serves the full control room with no extra steps.
#
#   bash scripts/build-pypi.sh
#
# Artifacts land in dist/pypi/. To publish (needs your PyPI API token, never
# committed — export it in your shell only):
#
#   export UV_PUBLISH_TOKEN="pypi-..."
#   uv publish dist/pypi/*
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="$ROOT/dist/pypi"

command -v npm >/dev/null || { echo "Node.js and npm are required to build the UI." >&2; exit 1; }
command -v uv >/dev/null || { echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }

if [[ ! -d web-ui/node_modules ]]; then
  npm --prefix web-ui ci
fi
npm --prefix web-ui run build
test -d web/dist || { echo "UI build did not produce web/dist." >&2; exit 1; }

mkdir -p "$OUT"
rm -f "$OUT"/ari_crew-*
# Wheel-only on purpose: the wheel bundles the prebuilt UI, and uv builds
# wheels from the sdist staging dir where hatch's web/ force-include mapping
# no longer resolves. Wheels are what pip/uvx install; no sdist is published.
uv build --wheel --out-dir "$OUT"

WHEEL="$(ls "$OUT"/ari_crew-*.whl | head -n 1)"
python3 - "$WHEEL" <<'EOF'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
need = ["kyn/web/dist/index.html", "kyn/cli.py", "kyn/server.py"]
missing = [path for path in need if not any(name.endswith(path) or name == path for name in names)]
if missing:
    print(f"WHEEL INCOMPLETE, missing: {missing}", file=sys.stderr)
    sys.exit(1)
print(f"Wheel OK: {len(names)} files, control room bundled.")
EOF

echo ""
shasum -a 256 "$OUT"/ari_crew-*
echo ""
echo "Publish with: export UV_PUBLISH_TOKEN='pypi-...'; uv publish dist/pypi/*"
