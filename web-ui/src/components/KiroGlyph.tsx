interface Props {
  size?: number;
  className?: string;
  title?: string;
}

/*
  Pac-Man body (circle with a 60° wedge cut on the right) plus a single
  off-axis eye punched through with evenodd. The eye is the "alien" tell —
  a plain Pac-Man has no eye, or has one dead-centered above the mouth.
*/
export function KiroGlyph({ size = 28, className, title }: Props) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M16 16 L28.12 9 A14 14 0 1 0 28.12 23 Z M12.8 11 a1.8 1.8 0 1 0 -3.6 0 a1.8 1.8 0 1 0 3.6 0"
      />
    </svg>
  );
}
