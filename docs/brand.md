# Ari brand

Ari is a calm, capable workspace for a colorful crew of distinct coding bots.
The product shell uses graphite, paper, and silver. Bot artwork keeps its own
bright color so each helper remains recognizable.

## Visual system

- Light surfaces use cool paper white and restrained graphite text.
- Dark surfaces use matte charcoal layers with soft neutral highlights.
- Gradients stay close to white, silver, and graphite; avoid a purple cast.
- Reserve strong color for bot characters, status, and meaningful actions.
- Use thin, quiet borders and rounded panels to make the interface feel
  considered without outlining every element.
- Use the shared spacing, type, elevation, and corner tokens in
  `web-ui/src/styles/tokens.css`.

## Bot artwork

Each Ari bot has a deterministic, name-generated character. Keep the individual
bot colors and silhouettes intact in chat, handoff, inbox, and task surfaces.
Do not recolor the characters to match the graphite application shell.

## Assets

- `web-ui/public/brand-mark.svg` — Ari crew mark.
- `web-ui/public/favicon.svg` — browser and PWA icon.
- `web/logo.svg` and `web/favicon.svg` — fallback control-room marks.
- `web-ui/src/components/AriGlyph.tsx` — inline brand mark used by the app and
  marketing pages.
- `web-ui/src/components/AriHelper.tsx` and `BotAvatar.tsx` — bot identity art.
- `docs/ari-logo-options.svg` — earlier logo concepts.

## Naming and attribution

- Write the product name as **Ari**.
- Use “bot” for a named Ari identity and “engine” for Kiro, OpenCode, or Codex.
- Keep each engine name attached only to its own integration.
- Ari is an independent product and is not an official distribution of those
  tools.
