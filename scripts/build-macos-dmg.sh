#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCH="$(uname -m)"
BUILD_ROOT="${ARI_MACOS_BUILD_DIR:-${KYN_MACOS_BUILD_DIR:-$ROOT/dist/ari-macos-$(date -u +%Y%m%dT%H%M%S)}}"
APP="$BUILD_ROOT/Ari.app"
STAGE="$BUILD_ROOT/dmg-stage"

if [[ "$ARCH" != "arm64" && "$ARCH" != "x86_64" ]]; then
  echo "Unsupported Mac architecture: $ARCH" >&2
  exit 1
fi
if [[ -e "$BUILD_ROOT" ]]; then
  echo "Build output already exists at $BUILD_ROOT. Move it aside before rebuilding." >&2
  exit 1
fi
command -v npm >/dev/null || { echo "Node.js and npm are required to build the UI." >&2; exit 1; }
command -v uv >/dev/null || { echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }

mkdir -p "$BUILD_ROOT"

if [[ ! -d "$ROOT/web-ui/node_modules" ]]; then
  npm --prefix "$ROOT/web-ui" ci
fi
ARI_DESKTOP_OUT_DIR="$BUILD_ROOT/web-dist" npm --prefix "$ROOT/web-ui" run build

export UV_CACHE_DIR="${TMPDIR:-/tmp}/ari-uv-cache"
uv run --project "$ROOT" --extra server --with pyinstaller -- \
  python -m PyInstaller \
    --noconfirm --clean --onefile \
    --name AriServer \
    --paths "$ROOT/src" \
    --distpath "$BUILD_ROOT/pyinstaller-dist" \
    --workpath "$BUILD_ROOT/pyinstaller-build" \
    --specpath "$BUILD_ROOT" \
    --add-data "$BUILD_ROOT/web-dist:kyn/web/dist" \
    "$ROOT/scripts/desktop_server_entry.py"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$STAGE"
cp "$BUILD_ROOT/pyinstaller-dist/AriServer" "$APP/Contents/Resources/AriServer"
cp "$ROOT/macos/AriLauncher.sh" "$APP/Contents/MacOS/Ari"
cp "$ROOT/macos/Ari.icns" "$APP/Contents/Resources/Ari.icns"
chmod 755 "$APP/Contents/MacOS/Ari" "$APP/Contents/Resources/AriServer"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Ari</string>
  <key>CFBundleDisplayName</key><string>Ari</string>
  <key>CFBundleIdentifier</key><string>dev.ari.desktop</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Ari</string>
  <key>CFBundleIconFile</key><string>Ari.icns</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
</dict>
</plist>
PLIST
printf 'APPL????' > "$APP/Contents/PkgInfo"

codesign --force --deep --sign - "$APP"
cp -R "$APP" "$STAGE/Ari.app"
ln -s /Applications "$STAGE/Applications"
DMG="$BUILD_ROOT/Ari-macOS-$ARCH.dmg"
if [[ -e "$DMG" ]]; then
  echo "Refusing to overwrite $DMG" >&2
  exit 1
fi
TEMP_IMAGE_DIR="$(mktemp -d /private/tmp/ari-dmg.XXXXXX)"
TEMP_DMG="$TEMP_IMAGE_DIR/Ari.dmg"
hdiutil create -volname "Ari" -srcfolder "$STAGE" -ov -format UDZO "$TEMP_DMG"
cp "$TEMP_DMG" "$DMG"
echo "Created $DMG"
