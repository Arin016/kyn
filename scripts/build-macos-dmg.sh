#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCH="$(uname -m)"
BUILD_ROOT="${ARI_MACOS_BUILD_DIR:-${KYN_MACOS_BUILD_DIR:-$ROOT/dist/ari-macos-$(date -u +%Y%m%dT%H%M%S)}}"
APP="$BUILD_ROOT/Ari.app"
STAGE="$BUILD_ROOT/dmg-stage"
ARI_DISTRIBUTION="${ARI_DISTRIBUTION:-0}"
DEVELOPER_ID="${ARI_DEVELOPER_ID_IDENTITY:-}"
NOTARY_PROFILE="${ARI_NOTARY_PROFILE:-}"

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
command -v clang >/dev/null || { echo "Xcode Command Line Tools (clang) are required to build the native app window." >&2; exit 1; }
if [[ "$ARI_DISTRIBUTION" == "1" ]]; then
  command -v xcrun >/dev/null || { echo "Xcode Command Line Tools (xcrun) are required for notarization." >&2; exit 1; }
  command -v security >/dev/null || { echo "The macOS security tool is required to check signing identities." >&2; exit 1; }
  [[ -n "$DEVELOPER_ID" ]] || { echo "Set ARI_DEVELOPER_ID_IDENTITY to your Developer ID Application identity." >&2; exit 1; }
  [[ -n "$NOTARY_PROFILE" ]] || { echo "Set ARI_NOTARY_PROFILE to a notarytool Keychain profile." >&2; exit 1; }
  identities="$(security find-identity -v -p codesigning)"
  [[ "$identities" == *"$DEVELOPER_ID"* ]] || {
    echo "The requested Developer ID Application identity is not available in the login keychain." >&2
    exit 1
  }
fi

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
cp "$ROOT/macos/Ari.icns" "$APP/Contents/Resources/Ari.icns"
clang -fobjc-arc -O -framework AppKit -framework WebKit -framework Foundation \
  "$ROOT/macos/AriApp.m" \
  -o "$APP/Contents/MacOS/Ari"
chmod 755 "$APP/Contents/MacOS/Ari" "$APP/Contents/Resources/AriServer"
test -x "$APP/Contents/MacOS/Ari" || { echo "Native Ari app executable was not produced." >&2; exit 1; }

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
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST
printf 'APPL????' > "$APP/Contents/PkgInfo"

if [[ "$ARI_DISTRIBUTION" == "1" ]]; then
  codesign --force --options runtime --timestamp --sign "$DEVELOPER_ID" \
    "$APP/Contents/Resources/AriServer"
  codesign --force --options runtime --timestamp --sign "$DEVELOPER_ID" \
    "$APP"
else
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict --verbose=2 "$APP"
if [[ "$ARI_DISTRIBUTION" == "1" ]]; then
  ditto -c -k --keepParent "$APP" "$BUILD_ROOT/Ari-notarization.zip"
  xcrun notarytool submit "$BUILD_ROOT/Ari-notarization.zip" \
    --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
  spctl --assess --type execute --verbose=2 "$APP"
fi
ditto "$APP" "$STAGE/Ari.app"
test -x "$STAGE/Ari.app/Contents/MacOS/Ari" || { echo "Staged Ari app is missing its executable." >&2; exit 1; }
test -x "$STAGE/Ari.app/Contents/Resources/AriServer" || { echo "Staged Ari app is missing its local service." >&2; exit 1; }
codesign --verify --deep --strict --verbose=2 "$STAGE/Ari.app"
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
hdiutil verify "$DMG"
VERIFY_MOUNT="$BUILD_ROOT/dmg-verify"
mkdir "$VERIFY_MOUNT"
hdiutil attach -readonly -nobrowse -mountpoint "$VERIFY_MOUNT" "$DMG"
trap 'hdiutil detach "$VERIFY_MOUNT" -quiet >/dev/null 2>&1 || true; rmdir "$VERIFY_MOUNT" 2>/dev/null || true' EXIT
test -x "$VERIFY_MOUNT/Ari.app/Contents/MacOS/Ari" || { echo "The created DMG is missing Ari.app's executable." >&2; exit 1; }
test -x "$VERIFY_MOUNT/Ari.app/Contents/Resources/AriServer" || { echo "The created DMG is missing Ari's local service." >&2; exit 1; }
codesign --verify --deep --strict --verbose=2 "$VERIFY_MOUNT/Ari.app"
hdiutil detach "$VERIFY_MOUNT" -quiet
rmdir "$VERIFY_MOUNT"
trap - EXIT
if [[ "$ARI_DISTRIBUTION" == "1" ]]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  hdiutil verify "$DMG"
fi
echo "Created $DMG"
