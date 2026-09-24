/** A tiny Ari helper character, used to give individual agents distinct avatars. */
export const ARI_HELPER_VIEWBOX = "0 0 64 64";

export const ARI_HELPER_PATH =
  "M32 9c-13 0-20 8-20 21v12c0 11 8 18 20 18s20-7 20-18V30C52 17 45 9 32 9Z";

export const ARI_HELPER_GLOSS_PATH = "M19 20c2.6-4.8 6.7-7.2 12.6-7.2";

export const ARI_HELPER_EYES = [
  { cx: 25, cy: 32, rx: 3.1, ry: 3.7 },
  { cx: 39, cy: 32, rx: 3.1, ry: 3.7 },
] as const;

const INK = "#171922";
const PAPER = "#ffffff";

export type HelperTone = "paper" | "ink" | "outline";

interface Props {
  tone?: HelperTone;
  weight?: number;
  className?: string;
  fill?: string;
  edge?: string;
  eye?: string;
  highlight?: string;
  gloss?: boolean;
}

export function AriHelper({
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
  const glossStroke = highlight ?? (tone === "paper" ? "rgba(23, 25, 34, 0.14)" : "rgba(255, 255, 255, 0.22)");

  return (
    <g className={className}>
      <path
        d={ARI_HELPER_PATH}
        fill={bodyFill}
        stroke={bodyEdge}
        strokeWidth={weight}
        strokeLinejoin="round"
      />
      <path d="M32 10V5" fill="none" stroke={bodyEdge} strokeWidth={weight} strokeLinecap="round" />
      <circle cx="32" cy="4" r="2.3" fill={eyeFill} />
      <rect
        x="19"
        y="26"
        width="26"
        height="13"
        rx="6.5"
        fill={tone === "outline" ? "none" : bodyEdge}
        stroke={tone === "outline" ? bodyEdge : "none"}
        strokeWidth={tone === "outline" ? weight : 0}
      />
      {ARI_HELPER_EYES.map((item, index) => (
        <ellipse key={index} cx={item.cx} cy={item.cy} rx={item.rx} ry={item.ry} fill={eyeFill} />
      ))}
      <path d="M25 60v3m14-3v3" fill="none" stroke={bodyEdge} strokeWidth={weight} strokeLinecap="round" />
      {gloss && (
        <path
          d={ARI_HELPER_GLOSS_PATH}
          fill="none"
          stroke={glossStroke}
          strokeWidth="2"
          strokeLinecap="round"
        />
      )}
    </g>
  );
}
