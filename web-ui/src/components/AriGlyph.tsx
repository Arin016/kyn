interface Props {
  size?: number;
  className?: string;
  title?: string;
  tone?: "paper" | "ink";
  finish?: "standard" | "silver";
}

function ParadeHelper({
  x,
  y,
  scale,
  color,
  shape = "round",
  antenna = "dot",
}: {
  x: number;
  y: number;
  scale: number;
  color: string;
  shape?: "round" | "square" | "tall";
  antenna?: "dot" | "fork" | "none";
}) {
  const body = shape === "square"
    ? <rect x="-8" y="-12" width="16" height="23" rx="5" />
    : shape === "tall"
      ? <path d="M-7 11V-5c0-8 3.5-12 7-12s7 4 7 12v16c0 5-3 8-7 8s-7-3-7-8Z" />
      : <rect x="-8" y="-12" width="16" height="23" rx="8" />;
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} fill={color} stroke={color} strokeLinecap="round" strokeLinejoin="round">
      {antenna === "fork" ? (
        <path d="M0-12v-5m0 2-4-4m4 4 4-4" fill="none" strokeWidth="2.5" />
      ) : antenna === "dot" ? (
        <><path d="M0-12v-4" fill="none" strokeWidth="2.5" /><circle cx="0" cy="-18" r="2.5" stroke="none" /></>
      ) : null}
      {body}
      <rect x="-5.8" y="-5" width="11.6" height="7.3" rx="3.6" fill="#181a21" stroke="none" />
      <circle cx="-2.3" cy="-1.3" r="1.15" fill="#fff" stroke="none" />
      <circle cx="2.3" cy="-1.3" r="1.15" fill="#fff" stroke="none" />
      <path d="M-4 11v3m8-3v3" fill="none" strokeWidth="2.5" />
    </g>
  );
}

/** Ari’s Parade: a small cast of different helper bots, not a single mascot. */
export function AriGlyph({ size = 28, className, title }: Props) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {title && <title>{title}</title>}
      <path d="M7 48c12 5 38 5 50 0" fill="none" stroke="#777985" strokeWidth="1.5" strokeDasharray="2 4" />
      <ParadeHelper x={12} y={39} scale={0.67} color="#8bd9c2" />
      <ParadeHelper x={23} y={36} scale={0.82} color="#b7a5ff" shape="square" antenna="fork" />
      <ParadeHelper x={34} y={32} scale={1} color="#f4775d" shape="tall" />
      <ParadeHelper x={46} y={36} scale={0.82} color="#83b9ff" shape="square" antenna="fork" />
      <ParadeHelper x={56} y={39} scale={0.67} color="#ffbd67" />
    </svg>
  );
}
