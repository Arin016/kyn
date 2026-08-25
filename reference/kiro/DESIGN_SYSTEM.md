# Kiro visual reference

Measured from the rendered `https://kiro.dev/` homepage on 26 August 2026. These are design observations, not copied source or brand assets. Kiro Bot keeps its own identity and product content.

## Direction

- Technical, editorial, and deliberately sparse rather than dashboard-like.
- True-black canvas with bright neutral type and one saturated violet action color.
- Large mono-rounded display type supplies character; supporting text is quieter and conventional.
- Flat sections and fine rules carry hierarchy. Shadows, glass effects, and ornamental gradients are absent from the primary composition.
- Asymmetry is intentional: the desktop hero gives most width to the statement and a narrow column to timely updates.

## Measured desktop reference

Reference viewport: 1280 × 720, DPR 2.

| Token | Measurement |
| --- | --- |
| Page background | `#000000` |
| Primary foreground | approximately `#fafafa` |
| Primary violet | `#9147ff` |
| Navigation height | `75px` |
| Hero content left edge | `175px` |
| Hero heading top | `195px` |
| Hero heading width | `739px` |
| Hero heading | `60px / 66px`, weight 700, `-1.8px` tracking |
| Body base | `16px / 24px` |
| Primary action | `48px` tall, `12px 24px`, `16px` radius |
| Primary action type | `16px / 24px`, weight 500 |

The live site uses AWS Diatype and AWS Diatype Rounded Semi Mono. Those fonts are proprietary to that presentation; this project uses locally bundled Space Grotesk and Inter as behaviorally similar substitutes.

## Measured mobile reference

Reference viewport: 390 × 844.

| Token | Measurement |
| --- | --- |
| Horizontal gutter | `24px` |
| Navigation height | `72px` |
| Hero heading top | `152px` |
| Hero heading width | `342px` |
| Hero heading | approximately `44.3px / 48.7px`, `-1.33px` tracking |
| Lead | approximately `19px / 26.6px` |
| Actions | full content width, vertically stacked |
| Updates rail | moves below hero actions |

## Project tokens

```css
--page: #000000;
--surface: #0b0b0c;
--surface-raised: #111113;
--ink: #fafafa;
--ink-soft: #b8b8bf;
--ink-faint: #7f7f88;
--rule: rgba(255, 255, 255, 0.12);
--violet: #9147ff;
--violet-hover: #a563ff;
--display: "Space Grotesk Variable", ui-monospace, sans-serif;
--body: "Inter Variable", system-ui, sans-serif;
--mono: ui-monospace, "SF Mono", Menlo, monospace;
--container: 1184px;
--gutter-desktop: 32px;
--gutter-mobile: 24px;
--nav-height: 75px;
--action-height: 48px;
--action-radius: 16px;
```

## Component rules

- Navigation stays flat and compact. Collapse secondary links instead of squeezing them.
- Desktop hero: statement plus narrow updates rail. Mobile hero: one column.
- Keep headings as strong blocks; do not add decorative gradient text.
- Use a solid violet primary action and a quiet outlined secondary action.
- Code and terminal surfaces use near-black, compact mono type, restrained borders, and no neon glow.
- Prefer shared rules, columns, and editorial rhythm over isolated rounded cards.
- When a card is required, keep the surface flat, border faint, and radius modest.

## Responsive behavior

- At approximately 1000px, collapse the hero rail below the statement.
- At 800px and below, hide secondary navigation and stack important actions.
- At 390px, preserve 24px gutters and make actions full width.
- Do not allow headings, code blocks, or management tables to create horizontal overflow.

## Motion and accessibility

- Motion should clarify entry and hierarchy: short opacity/vertical reveals only.
- Honor `prefers-reduced-motion`.
- Preserve visible keyboard focus, semantic landmarks, accessible labels, and adequate contrast.

## Visual QA checklist

- Compare reference and local page at matching viewports.
- Check silhouette, x/y alignment, content width, heading wrap, section height, action geometry, rail placement, and mobile overflow.
- Reload after code changes before taking the next screenshot.
- Verify navigation, buttons, scrolling, focus, reduced motion, and the control-room entry path.
