# Kiro Bot brand mark

The Kiro Bot mark is the **night ghost**: a dark, agent-like silhouette edged in electric violet. The silhouette is the signature; it never carries a letter or word inside its body.

It combines the approachable ghost language from the supplied references with the product's local-first, dark control-room identity. The result is intentionally not a white Kiro ghost pasted onto a purple square.

## Palette

- Graphite highlight: `#292332`
- Near-black body: `#07070A`
- Soft violet: `#D7C2FF`
- Electric violet: `#A66BFF`
- Deep violet: `#6D22DD`

## Assets

- `web-ui/public/brand-mark.svg` — transparent standalone mark for documentation and product surfaces.
- `web-ui/public/favicon.svg` — compact mark on a rounded dark tile.
- `web/logo.svg` and `web/favicon.svg` — equivalents used by the dependency-free fallback UI.
- `web-ui/src/components/KiroGlyph.tsx` — inline React version used by the landing page, engineering page, control room, sidebar, and footer.
- `web-ui/src/components/PixelKiro.tsx` — the living hero field, which continuously assembles the ghost and Kiro wordform from streaming pixels.

## Usage

- Keep the mark on black, graphite, white, or very light neutral backgrounds.
- Preserve its aspect ratio and do not recolor individual features.
- Keep the standalone mark letter-free. The animated hero may form the Kiro word externally as a transient particle state.
- At sizes below 20px, prefer the favicon tile.
- Do not pair it with the standalone Kiro wordmark or imply that this independent project is an official Kiro distribution.
