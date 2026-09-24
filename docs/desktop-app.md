# macOS app and iPhone access

The macOS app is a local shell around the Ari control room. It starts the
bundled Ari service on `127.0.0.1:8765`, then opens the first-run setup screen
in the default browser. The marketing site remains a separate Vercel build.
Ari data stays under `~/.ari`.

## Build an Apple Silicon DMG

On a Mac with Node.js and `uv`:

```bash
bash scripts/build-macos-dmg.sh
```

The script prints the path to a new `dist/ari-macos-<timestamp>/Ari-macOS-arm64.dmg`
(or `x86_64` on an Intel Mac). It builds the React UI, bundles the Python
service, and places both in a small macOS app wrapper. Each DMG is built for the
architecture of the Mac running the script. Build a second time on an Intel Mac
to produce the Intel artifact.

This development build is ad-hoc signed. Before sharing it as a smooth public
download, sign it with a Developer ID certificate and notarize it; the build
script does not claim Gatekeeper-ready distribution. Add the signing and
notarization credentials in the release environment before publishing a DMG.

## First run

The setup screen checks for `kiro-cli`, `opencode`, and `codex-acp`. Selecting
**Install CLI** runs the selected engine's published installer; Codex setup
installs OpenAI's Codex CLI and the Agent Client Protocol adapter through npm.
Codex setup requires Node.js and npm. Nothing is installed until you press the
button. Then sign in to the selected engine from the commands shown in setup.
Ari does not collect engine credentials.

The app contains the Ari server and control room, but does not bundle Kiro,
OpenCode, or Codex. Each engine retains its own installation, account, and
update flow. Ari does not collect engine credentials.

Once connected, create bots for different projects and roles. You can move a
task between Kiro, OpenCode, and Codex with a handoff brief, then track its
status in the Work inbox. Coding tasks and plugin connections are managed in
the Ari control room.

## iPhone

Ari's control room is responsive and installable as a web app. The setup screen
shows the Tailscale Serve command for keeping the Mac service loopback-only
while making it available to authenticated devices in the same tailnet. Install
Tailscale and sign in on both devices, run `tailscale serve --bg 8765` on the
Mac, then open the HTTPS URL Tailscale prints in Safari and choose **Share → Add
to Home Screen**. Review tailnet access rules before sharing access with anyone
else. Do not use Tailscale Funnel or expose port 8765 publicly.
