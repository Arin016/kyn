import { useId } from "react";

interface Props {
  size?: number;
  className?: string;
  title?: string;
}

export function KiroGlyph({ size = 28, className, title }: Props) {
  const id = useId().replaceAll(":", "");
  const bodyGradient = `kiro-body-${id}`;
  const edgeGradient = `kiro-edge-${id}`;

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
      <defs>
        <linearGradient id={bodyGradient} x1="13" y1="8" x2="51" y2="58" gradientUnits="userSpaceOnUse">
          <stop stopColor="#292332" />
          <stop offset="0.48" stopColor="#15121C" />
          <stop offset="1" stopColor="#07070A" />
        </linearGradient>
        <linearGradient id={edgeGradient} x1="10" y1="6" x2="55" y2="59" gradientUnits="userSpaceOnUse">
          <stop stopColor="#D7C2FF" />
          <stop offset="0.38" stopColor="#A66BFF" />
          <stop offset="1" stopColor="#6D22DD" />
        </linearGradient>
      </defs>
      <path
        d="M31.8 5.5c-12.8 0-19.4 7.7-20.4 19.8l-.7 8.4c-.3 3.5-1.5 6.5-4.1 9.9-1.8 2.4-.8 5.9 2 7.1 3.5 1.6 7.4.5 10.5-1.2-1.3 5.5 1.4 9.4 5.8 9.9 3.7.4 7.4-1.3 10.5-3.4 1.4 4.2 5.1 5 8.6 3.4 9.1-4.1 13.8-15.5 13.8-28.1C57.8 14.8 47.6 5.5 31.8 5.5Z"
        fill={`url(#${bodyGradient})`}
        stroke={`url(#${edgeGradient})`}
        strokeWidth="2.6"
        strokeLinejoin="round"
      />
      <ellipse cx="29" cy="24" rx="3.25" ry="5.25" fill="#C39AFF" />
      <ellipse cx="41.5" cy="24" rx="3.25" ry="5.25" fill="#A86CFF" />
      <path d="M28.5 37v12m0-5.5 7.5-7M31 42l7.5 7" fill="none" stroke={`url(#${edgeGradient})`} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" opacity=".82" />
      <path d="M17 18c2.8-5.5 7.8-8.3 14.8-8.3" fill="none" stroke="#FFFFFF" strokeOpacity=".16" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
