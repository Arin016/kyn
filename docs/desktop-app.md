# macOS app and iPhone access

The macOS app opens a native window and displays the Ari control room in the
system WebKit view. It starts the bundled Ari service on `127.0.0.1:8765` and
keeps the first-run setup inside the app; external links open in the browser.
The marketing site remains a separate Vercel build. Ari data stays under
`~/.ari`.

## Build an Apple Silicon DMG

On a Mac with Node.js, `uv`, and Xcode Command Line Tools:

```bash
bash scripts/build-macos-dmg.sh
```

The script prints the path to a new `dist/ari-macos-<timestamp>/Ari-macOS-arm64.dmg`
(or `x86_64` on an Intel Mac). It builds the React UI, bundles the Python
service, compiles the native AppKit/WebKit window, and places them in the app
bundle. Each DMG is built for the architecture of the Mac running the script.
Build a second time on an Intel Mac to produce the Intel artifact.

The default development build is ad-hoc signed and is not suitable as a
Gatekeeper-ready public download. Use the official distribution mode below for
friend or public downloads.

For an official distribution build, install a Developer ID Application
certificate in the login keychain and create a `notarytool` Keychain profile.
Then set `ARI_DISTRIBUTION=1`, `ARI_DEVELOPER_ID_IDENTITY`, and
`ARI_NOTARY_PROFILE` when running the build script. The script signs the
embedded service and app with hardened runtime, submits the app and DMG for
notarization, staples tickets, and checks Gatekeeper. Keep all credentials in
the local keychain; never commit them to the repository.

## First run

The setup page scrolls inside the app window when its content is taller than
the available window height. The window can be resized, and the setup remains
usable on smaller displays.

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
