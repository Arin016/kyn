/**
 * KYN mark — the one logo (night ghost).
 *
 * Rendered as a bare <g> so it composes inside any <svg> (glyph buttons, bot
 * avatars, workflow nodes). Three tones cover the app:
 *   - "paper": white body, ink outline — for light surfaces
 *   - "ink":   ink body, paper outline — for dark / inverted surfaces
 *   - "outline": no fill, ink line art
 *
 * Every tone can be overridden colour-by-colour (`fill`, `edge`, `eye`,
 * `highlight`) so bot avatars can tint the same shape without a second path.
 */
export const KYN_VIEWBOX = "0 0 64 64";

export const KYN_BODY_PATH =
  "M31.8 5.5c-12.8 0-19.4 7.7-20.4 19.8l-.7 8.4c-.3 3.5-1.5 6.5-4.1 9.9-1.8 2.4-.8 5.9 2 7.1 3.5 1.6 7.4.5 10.5-1.2-1.3 5.5 1.4 9.4 5.8 9.9 3.7.4 7.4-1.3 10.5-3.4 1.4 4.2 5.1 5 8.6 3.4 9.1-4.1 13.8-15.5 13.8-28.1C57.8 14.8 47.6 5.5 31.8 5.5Z";

export const KYN_HIGHLIGHT_PATH = "M17 18c2.8-5.5 7.8-8.3 14.8-8.3";

export const KYN_EYES = [
  { cx: 29, cy: 24, rx: 3.25, ry: 5.25 },
  { cx: 41.5, cy: 24, rx: 3.25, ry: 5.25 },
] as const;

const INK = "#0b0e0b";
const PAPER = "#ffffff";

export type MarkTone = "paper" | "ink" | "outline";

interface Props {
  tone?: MarkTone;
  /** Outline weight; the mark stays legible from 16px up. */
  weight?: number;
  className?: string;
  fill?: string;
  edge?: string;
  eye?: string;
  highlight?: string;
  /** Draw the upper-left gloss stroke. */
  gloss?: boolean;
}

export function KynMark({
  tone = "paper",
  weight = 2.8,
  className,
  fill,
  edge,
  eye,
  highlight,
  gloss = true,
}: Props) {
  const bodyFill = fill ?? (tone === "paper" ? PAPER : tone === "outline" ? "none" : INK);
  const bodyEdge = edge ?? (tone === "paper" ? INK : PAPER);
  const eyeFill = eye ?? (tone === "paper" ? INK : PAPER);
  const glossStroke =
    highlight ?? (tone === "paper" ? "rgba(11, 20, 12, 0.14)" : "rgba(255, 255, 255, 0.22)");

  return (
    <g className={className}>
      <path
        d={KYN_BODY_PATH}
        fill={bodyFill}
        stroke={bodyEdge}
        strokeWidth={weight}
        strokeLinejoin="round"
      />
      {KYN_EYES.map((item, index) => (
        <ellipse key={index} cx={item.cx} cy={item.cy} rx={item.rx} ry={item.ry} fill={eyeFill} />
      ))}
      {gloss && (
        <path
          d={KYN_HIGHLIGHT_PATH}
          fill="none"
          stroke={glossStroke}
          strokeWidth="2"
          strokeLinecap="round"
        />
      )}
    </g>
  );
}
