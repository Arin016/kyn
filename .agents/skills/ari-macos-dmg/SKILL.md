---
name: ari-macos-dmg
description: Build and verify Ari's macOS desktop DMG from this repository when asked to refresh, package, or prepare the app for Mac testing.
---

# Build Ari for macOS

Use the repository's `scripts/build-macos-dmg.sh` to package the current checkout.
Read [the desktop app notes](../../../docs/desktop-app.md) if release or setup
details matter, and inspect the script before changing its packaging behavior.

## Build

The build requires macOS, Node.js/npm, `uv`, and Xcode Command Line Tools
(`clang`, `codesign`, and `hdiutil`). It builds the web UI, freezes the local
Python service with PyInstaller, compiles the native AppKit/WebKit window,
assembles `Ari.app`, and creates a compressed DMG.

Run from the repository root:

```bash
bash scripts/build-macos-dmg.sh
```

The script writes a new directory under `dist/ari-macos-<UTC timestamp>/` and
prints the DMG path. It refuses to overwrite an existing build directory. To
choose a stable, unused output directory, set `ARI_MACOS_BUILD_DIR`, for example:

```bash
ARI_MACOS_BUILD_DIR="$PWD/dist/ari-macos-device-test" bash scripts/build-macos-dmg.sh
```

The artifact targets the architecture of the Mac running the build: Apple
Silicon (`arm64`) or Intel (`x86_64`). Build on the target architecture; this
script does not create a universal binary. If npm or `uv` cannot fetch a
dependency because network access is restricted, request the required network
permission and retry the same build rather than editing generated artifacts.

## Verify and report

After a successful build:

1. Confirm both `Ari.app/Contents/MacOS/Ari` and
   `Ari.app/Contents/Resources/AriServer` exist and are executable in the build
   bundle, staged bundle, and a read-only mount of the finished DMG. Run
   `codesign --verify --deep --strict` on each app bundle and require success.
2. Run `hdiutil verify <path-to-dmg>` and confirm it reports a valid checksum.
3. Confirm the DMG exists and report its full path, size, and target
   architecture. Include its SHA-256 when useful for transferring the file.
4. Keep the app's signing status clear: the current script applies an ad-hoc
   signature. A smooth public download requires Developer ID signing and
   notarization, which this script does not perform.

## Official distribution

For public distribution or Macs managed by endpoint security, use Apple's
Developer ID and notarization flow. It requires a valid Developer ID
Application identity installed in the login keychain and a `notarytool`
Keychain profile created on the build Mac. Never put certificate private keys,
Apple passwords, or notary credentials in the repository or chat.

With those prerequisites configured, run:

```bash
ARI_DISTRIBUTION=1 \
ARI_DEVELOPER_ID_IDENTITY="Developer ID Application: Publisher Name (TEAMID)" \
ARI_NOTARY_PROFILE="ari-notary" \
bash scripts/build-macos-dmg.sh
```

Distribution mode signs the embedded service and app with the Developer ID,
enables the hardened runtime and secure timestamps, submits the app and DMG to
Apple's notary service, staples the tickets, and checks Gatekeeper. Do not call
an ad-hoc build notarized or use it as the public release artifact.

Do not commit, push, publish, or upload the artifact unless the user explicitly
asks for that action. The build output is local and can be shared with the user
for device testing.
