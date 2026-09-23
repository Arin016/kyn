import { useId } from "react";
import { KYN_VIEWBOX, KynMark } from "./KynMark";

/**
 * Bot avatars — always the KYN ghost, never a letter.
 *
 * The mark is the brand shape unchanged; each bot gets a stable colour family
 * and one of eight treatments, so a list of bots reads like a contact list
 * instead of a wall of identical dots. Colour is deterministic from the name,
 * so a bot keeps its face everywhere it appears.
 */
const INK = "#0b0e0b";
const PAPER = "#ffffff";

interface Hue {
  deep: string;
  mid: string;
  bright: string;
}

// Deep stops stay saturated rather than near-black: the tint has to read at
// 28px in a message row, not just at avatar size in a profile card.
const HUES: Hue[] = [
  { deep: "#2d1a63", mid: "#6d3ff0", bright: "#c9b1ff" }, // violet
  { deep: "#1d2a6b", mid: "#3d5be0", bright: "#a5b8ff" }, // indigo
  { deep: "#083c50", mid: "#0e93b5", bright: "#8fe4f5" }, // cyan
  { deep: "#083c2c", mid: "#16a06b", bright: "#86efc0" }, // emerald
  { deep: "#4d3006", mid: "#d0860f", bright: "#ffd88a" }, // amber
  { deep: "#50102c", mid: "#d13c78", bright: "#ffa8cb" }, // rose
  { deep: "#4e1708", mid: "#dd5326", bright: "#ffae8b" }, // ember
  { deep: "#1c242c", mid: "#4a5a68", bright: "#c6d2dc" }, // slate
];

const MONO: Hue = { deep: "#0b0e0b", mid: "#3a423a", bright: "#f4f7f3" };

/** Stable, order-independent name hash. FNV-1a + murmur3 finalizer. */
export function avatarSeed(name: string): number {
  const value = (name || "kyn").trim().toLowerCase();
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
  /** "color" (default) tints the mark; "mono" keeps it strictly ink & paper. */
  tone?: "color" | "mono";
  /** Follow the app theme instead of the fixed light/dark discs. */
  variant?: number;
}

export function BotAvatar({ name, size = 36, className, title, tone = "color", variant }: Props) {
  const uid = useId().replace(/:/g, "");
  const seed = avatarSeed(name);
  const label = title ?? name;
  const mono = tone === "mono" || (seed >>> 19) % 6 === 0;
  const hue = mono ? MONO : HUES[(seed >>> 3) % HUES.length];
  const shape = variant ?? (seed >>> 7) % 8;
  const tilt = ((seed >>> 13) % 15) - 7;
  const dark = shape !== 2 && shape !== 5;

  const edgeId = `${uid}-edge`;
  const bodyId = `${uid}-body`;
  const glowId = `${uid}-glow`;
  const glassId = `${uid}-glass`;
  const shadeId = `${uid}-shade`;
  const discId = `${uid}-disc`;
  const squircleId = `${uid}-squircle`;

  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox={KYN_VIEWBOX}
      role="img"
      aria-label={label}
      focusable="false"
    >
      <title>{label}</title>
      <defs>
        <linearGradient id={edgeId} x1="14" y1="8" x2="52" y2="58" gradientUnits="userSpaceOnUse">
          <stop stopColor={hue.bright} />
          <stop offset="0.45" stopColor={hue.mid} />
          <stop offset="1" stopColor={mono ? INK : hue.mid} />
        </linearGradient>
        <linearGradient id={bodyId} x1="12" y1="4" x2="54" y2="60" gradientUnits="userSpaceOnUse">
          <stop stopColor={hue.bright} />
          <stop offset="0.52" stopColor={hue.mid} />
          <stop offset="1" stopColor={hue.deep} />
        </linearGradient>
        <radialGradient id={glowId} cx="0.34" cy="0.26" r="0.9">
          <stop stopColor={hue.mid} stopOpacity="0.6" />
          <stop offset="1" stopColor={hue.mid} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={glassId} x1="10" y1="2" x2="52" y2="44" gradientUnits="userSpaceOnUse">
          <stop stopColor="#ffffff" stopOpacity="0.26" />
          <stop offset="0.55" stopColor="#ffffff" stopOpacity="0.04" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
        <linearGradient id={shadeId} x1="32" y1="32" x2="32" y2="64" gradientUnits="userSpaceOnUse">
          <stop stopColor="#000000" stopOpacity="0" />
          <stop offset="1" stopColor="#000000" stopOpacity="0.3" />
        </linearGradient>
        <clipPath id={discId}>
          <circle cx="32" cy="32" r="31" />
        </clipPath>
        <clipPath id={squircleId}>
          <rect x="1" y="1" width="62" height="62" rx="18" />
        </clipPath>
      </defs>

      <g clipPath={`url(#${shape === 3 ? squircleId : discId})`}>
        {/* 0 — night ghost: deep disc, hue-lit outline, glowing eyes */}
        {shape === 0 && (
          <>
            <circle cx="32" cy="32" r="31" fill={hue.deep} />
            <circle cx="32" cy="32" r="31" fill={`url(#${glowId})`} />
            <g transform="translate(7.5 7.5) scale(0.766)">
              <KynMark
                fill={`url(#${glassId})`}
                edge={`url(#${edgeId})`}
                eye={hue.bright}
                highlight="rgba(255, 255, 255, 0.22)"
                weight={2.7}
              />
            </g>
            <rect x="0" y="0" width="64" height="64" fill={`url(#${glassId})`} opacity="0.3" />
            <rect x="0" y="0" width="64" height="64" fill={`url(#${shadeId})`} />
          </>
        )}

        {/* 1 — solid ghost: hue gradient body on a deep disc */}
        {shape === 1 && (
          <>
            <circle cx="32" cy="32" r="31" fill={hue.deep} />
            <circle cx="32" cy="32" r="31" fill={`url(#${glowId})`} />
            <g transform="translate(7.5 7.5) scale(0.766)">
              <KynMark
                fill={`url(#${bodyId})`}
                edge="rgba(255, 255, 255, 0.92)"
                eye={mono ? PAPER : "#0b0e0b"}
                highlight="rgba(255, 255, 255, 0.4)"
                weight={2.2}
              />
            </g>
            <rect x="0" y="0" width="64" height="64" fill={`url(#${shadeId})`} />
          </>
        )}

        {/* 2 — paper disc, hue ghost (reads like a printed sticker) */}
        {shape === 2 && (
          <>
            <circle cx="32" cy="32" r="31" fill={PAPER} />
            <circle cx="32" cy="32" r="25.5" fill="none" stroke={hue.mid} strokeWidth="1.4" opacity="0.22" />
            <g transform="translate(9.5 9.5) scale(0.7)">
              <KynMark
                fill={`url(#${bodyId})`}
                edge={hue.deep}
                eye={PAPER}
                highlight="rgba(255, 255, 255, 0.55)"
                weight={2.6}
              />
            </g>
          </>
        )}

        {/* 3 — squircle app-icon: hue gradient plate, paper ghost */}
        {shape === 3 && (
          <>
            <rect x="0" y="0" width="64" height="64" fill={`url(#${bodyId})`} />
            <rect x="0" y="0" width="64" height="64" fill={`url(#${glassId})`} opacity="0.7" />
            <g transform="translate(8 8) scale(0.75)">
              <KynMark
                fill={PAPER}
                edge="rgba(4, 6, 4, 0.28)"
                eye={hue.deep}
                highlight="rgba(255, 255, 255, 0.5)"
                weight={2.2}
              />
            </g>
            <rect x="0" y="0" width="64" height="64" fill={`url(#${shadeId})`} opacity="0.7" />
          </>
        )}

        {/* 4 — ringed: paper ghost inside a hue halo */}
        {shape === 4 && (
          <>
            <circle cx="32" cy="32" r="31" fill={hue.deep} />
            <circle cx="32" cy="32" r="31" fill={`url(#${glowId})`} opacity="0.7" />
            <circle cx="32" cy="32" r="24.5" fill="none" stroke={`url(#${edgeId})`} strokeWidth="1.6" opacity="0.55" />
            <g transform="translate(9 9) scale(0.72)">
              <KynMark
                fill={PAPER}
                edge={hue.mid}
                eye={hue.mid}
                highlight="rgba(255, 255, 255, 0.45)"
                weight={2.4}
              />
            </g>
          </>
        )}

        {/* 5 — line art: hue outline on paper */}
        {shape === 5 && (
          <>
            <circle cx="32" cy="32" r="31" fill={PAPER} />
            <g transform="translate(8.5 8.5) scale(0.735)">
              <KynMark fill="none" edge={`url(#${bodyId})`} eye={hue.mid} weight={3.4} gloss={false} />
            </g>
          </>
        )}

        {/* 6 — close crop: the mark fills the frame */}
        {shape === 6 && (
          <>
            <circle cx="32" cy="32" r="31" fill={hue.deep} />
            <circle cx="32" cy="32" r="31" fill={`url(#${glowId})`} />
            <g transform="rotate(${tilt} 32 32) translate(-1.5 -4) scale(1.04)">
              <KynMark
                fill={mono ? INK : hue.deep}
                edge={hue.bright}
                eye={hue.bright}
                highlight="rgba(255, 255, 255, 0.18)"
                weight={2.4}
              />
            </g>
            <rect x="0" y="0" width="64" height="64" fill={`url(#${shadeId})`} />
          </>
        )}

        {/* 7 — flat plate: strong hue fill, paper ghost */}
        {shape === 7 && (
          <>
            <circle cx="32" cy="32" r="31" fill={`url(#${bodyId})`} />
            <circle cx="32" cy="32" r="31" fill={`url(#${glassId})`} opacity="0.5" />
            <g transform={`rotate(${tilt * 0.6} 32 32) translate(8 8) scale(0.75)`}>
              <KynMark
                fill={PAPER}
                edge="rgba(4, 6, 4, 0.22)"
                eye={hue.deep}
                highlight="rgba(255, 255, 255, 0.5)"
                weight={2.2}
              />
            </g>
            <rect x="0" y="0" width="64" height="64" fill={`url(#${shadeId})`} opacity="0.7" />
          </>
        )}
      </g>

      {shape !== 3 && (
        <circle
          cx="32"
          cy="32"
          r="30.5"
          fill="none"
          stroke={dark ? "rgba(255, 255, 255, 0.14)" : "rgba(11, 20, 12, 0.14)"}
        />
      )}
    </svg>
  );
}
