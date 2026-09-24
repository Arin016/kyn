/**
 * Name-generated Ari crew characters. The design is deterministic, so the same
 * bot looks identical in its roster row, direct chat, and group conversation.
 */
const CREW = [
  { body: "#f4775d", shade: "#d94c3d", glow: "#ffb39c" }, // coral
  { body: "#b7a5ff", shade: "#765de0", glow: "#e6ddff" }, // lilac
  { body: "#8bd9c2", shade: "#399d83", glow: "#d6fff2" }, // mint
  { body: "#83b9ff", shade: "#4678c5", glow: "#d6e9ff" }, // sky
  { body: "#ffbd67", shade: "#c47a28", glow: "#ffebc3" }, // butter
  { body: "#f08ab0", shade: "#bb4e7d", glow: "#ffdbea" }, // pink
];

const BODY_SHAPES = [
  "M32 11c-12 0-20 7-20 20v10c0 12 8 19 20 19s20-7 20-19V31c0-13-8-20-20-20Z",
  "M19 12h26a7 7 0 0 1 7 7v24c0 10-8 17-20 17s-20-7-20-17V19a7 7 0 0 1 7-7Z",
  "M32 8c-10 0-16 8-16 21v13c0 11 6 17 16 17s16-6 16-17V29C48 16 42 8 32 8Z",
  "M13 25c0-9 7-15 19-15s19 6 19 15v18c0 12-7 18-19 18s-19-6-19-18Z",
  "M21 9h22l8 12v22c0 10-7 16-19 16s-19-6-19-16V21Z",
  "M14 31c0-13 8-21 18-21s18 8 18 21v11c0 11-8 18-18 18s-18-7-18-18Z",
  "M18 13c4-5 10-7 14-7s10 2 14 7l7 13v17c0 10-8 16-21 16s-21-6-21-16V26Z",
  "M32 9c12 0 19 8 19 20v17c0 10-8 15-19 15s-19-5-19-15V29C13 17 20 9 32 9Z",
] as const;

/** Stable, order-independent name hash. */
export function avatarSeed(name: string): number {
  const value = (name || "ari").trim().toLowerCase();
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  hash ^= hash >>> 16;
  hash = Math.imul(hash, 2246822507);
  hash ^= hash >>> 13;
  hash = Math.imul(hash, 3266489909);
  hash ^= hash >>> 16;
  return hash >>> 0;
}

interface Props {
  name: string;
  size?: number;
  className?: string;
  title?: string;
  tone?: "color" | "mono";
  variant?: number;
}

function Body({ d, color, shade, outline }: { d: string; color: string; shade: string; outline: string }) {
  return (
    <>
      <path d={d} fill={color} stroke={outline} strokeWidth="2.2" strokeLinejoin="round" />
      <path d="M18 48c3 6 8 8 14 8s11-2 14-8" fill="none" stroke={shade} strokeWidth="2" opacity=".35" />
    </>
  );
}

export function BotAvatar({ name, size = 36, className, title, tone = "color", variant }: Props) {
  const seed = avatarSeed(name);
  const colorSet = CREW[(seed >>> 4) % CREW.length];
  const shape = (variant ?? (seed >>> 8) % BODY_SHAPES.length) % BODY_SHAPES.length;
  const antenna = (seed >>> 13) % 5;
  const face = (seed >>> 16) % 4;
  const badge = (seed >>> 20) % 5;
  const color = tone === "mono" ? "#d9dce1" : colorSet.body;
  const shade = tone === "mono" ? "#777c85" : colorSet.shade;
  const glow = tone === "mono" ? "#fff" : colorSet.glow;
  const backdrop = tone === "mono" ? "#272a30" : "#22242b";
  const label = title ?? name;
  const oneEye = face === 3;

  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={label}
      focusable="false"
    >
      <title>{label}</title>
      <circle cx="32" cy="32" r="31" fill={backdrop} />
      <circle cx="32" cy="32" r="28" fill="none" stroke="rgba(255,255,255,.1)" />

      {/* Name seed changes the silhouette and antenna, not just the color. */}
      {antenna === 0 && <><path d="M32 12V7" stroke={glow} strokeWidth="3" strokeLinecap="round"/><circle cx="32" cy="6" r="3" fill={color}/></>}
      {antenna === 1 && <><path d="M27 12V8m10 4V8" stroke={glow} strokeWidth="3" strokeLinecap="round"/><circle cx="27" cy="7" r="2" fill={color}/><circle cx="37" cy="7" r="2" fill={color}/></>}
      {antenna === 2 && <path d="M32 12V6l5-3" fill="none" stroke={glow} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>}
      {antenna === 3 && <><path d="M13 30H8m43 0h5" stroke={glow} strokeWidth="3" strokeLinecap="round"/><circle cx="7" cy="30" r="2.5" fill={color}/><circle cx="57" cy="30" r="2.5" fill={color}/></>}

      <Body d={BODY_SHAPES[shape]} color={color} shade={shade} outline="rgba(255,255,255,.66)" />

      <rect x={oneEye ? 21 : 17} y="26" width={oneEye ? 22 : 30} height="15" rx="7.5" fill="#20232a" />
      {oneEye ? (
        <><circle cx="32" cy="33.5" r="4.2" fill={glow}/><circle cx="33.5" cy="32.5" r="1.3" fill="#fff"/></>
      ) : (
        <><ellipse cx="26" cy="33" rx={face === 2 ? 2.5 : 3.2} ry="3.8" fill={glow}/><ellipse cx="38" cy="33" rx="3.2" ry="3.8" fill={glow}/><circle cx="27" cy="32" r="1.1" fill="#fff"/><circle cx="39" cy="32" r="1.1" fill="#fff"/></>
      )}
      {face === 1 ? <path d="M28 46h8" stroke={shade} strokeWidth="2.4" strokeLinecap="round"/> : <path d="M28 46c2.5 2.5 5.5 2.5 8 0" fill="none" stroke={shade} strokeWidth="2.4" strokeLinecap="round"/>}

      {/* Tiny personal mark: star, bolt, dot, fin, or no badge. */}
      {badge === 0 && <path d="m45 17 1.6 3.4 3.4 1.6-3.4 1.6L45 27l-1.6-3.4L40 22l3.4-1.6Z" fill={glow}/>}
      {badge === 1 && <path d="m18 18 4 3-4 3-4-3Z" fill={glow}/>}
      {badge === 2 && <circle cx="46" cy="20" r="2.5" fill={glow}/>}
      {badge === 3 && <path d="M44 43h6l-3 4h-6Z" fill={glow}/>}

      <path d="M24 59v2m16-2v2" stroke={glow} strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
