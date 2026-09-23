import { KYN_VIEWBOX, KynMark, type MarkTone } from "./KynMark";

interface Props {
  size?: number;
  className?: string;
  title?: string;
  /** "paper" for light surfaces, "ink" for inverted ones. */
  tone?: MarkTone;
}

export function KiroGlyph({ size = 28, className, title, tone = "paper" }: Props) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox={KYN_VIEWBOX}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {title && <title>{title}</title>}
      <KynMark tone={tone} />
    </svg>
  );
}
