import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

interface Props {
  x: number;
  y: number;
  clicking?: boolean;
  visible?: boolean;
  clickFrame?: number;
}

export const Cursor: React.FC<Props> = ({
  x,
  y,
  clicking = false,
  visible = true,
  clickFrame = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!visible) return null;

  const press = spring({
    frame: clicking ? Math.max(0, frame - clickFrame) : 0,
    fps,
    config: { damping: 18, stiffness: 220, mass: 0.4 },
  });
  const scale = clicking ? interpolate(press, [0, 1], [1, 0.86]) : 1;

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: 28,
        height: 28,
        transform: `translate(-4px, -2px) scale(${scale})`,
        zIndex: 1000,
        pointerEvents: "none",
        filter: "drop-shadow(0 2px 4px rgba(0,0,0,0.45))",
      }}
    >
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
        <path
          d="M5.5 3.2 18.8 11.1c.55.33.4 1.12-.24 1.22l-5.3.82 2.55 5.9c.22.5-.1 1.08-.63 1.16l-1.7.26c-.5.08-.98-.22-1.14-.7l-2.4-6.55-3.95 3.2c-.55.45-1.4.05-1.4-.65V4.05c0-.72.8-1.15 1.41-.85Z"
          fill="#ECECEC"
          stroke="#0A0A0A"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
      </svg>
      {clicking && (
        <div
          style={{
            position: "absolute",
            left: 2,
            top: 2,
            width: 18,
            height: 18,
            borderRadius: 999,
            border: "2px solid #B08BFF",
            opacity: interpolate(press, [0, 1], [0.7, 0]),
            transform: `scale(${interpolate(press, [0, 1], [0.4, 1.8])})`,
          }}
        />
      )}
    </div>
  );
};
