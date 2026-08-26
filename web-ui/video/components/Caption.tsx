import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

interface Props {
  text: string;
  subtext?: string;
  active: boolean;
  appearAt: number;
}

export const Caption: React.FC<Props> = ({ text, subtext, active, appearAt }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!active) return null;

  const enter = spring({
    frame: Math.max(0, frame - appearAt),
    fps,
    config: { damping: 16, stiffness: 120 },
  });
  const opacity = interpolate(enter, [0, 1], [0, 1]);
  const y = interpolate(enter, [0, 1], [18, 0]);

  return (
    <div
      style={{
        position: "absolute",
        left: 64,
        bottom: 56,
        zIndex: 900,
        maxWidth: 720,
        opacity,
        transform: `translateY(${y}px)`,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          display: "inline-flex",
          flexDirection: "column",
          gap: 6,
          padding: "14px 18px",
          borderRadius: 16,
          background: "rgba(10,10,10,0.82)",
          border: "1px solid rgba(176,139,255,0.28)",
          backdropFilter: "blur(10px)",
        }}
      >
        <span
          style={{
            fontFamily: '"Space Grotesk Variable", "Space Grotesk", Inter, sans-serif',
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.03em",
            color: "#FFFFFF",
          }}
        >
          {text}
        </span>
        {subtext ? (
          <span style={{ fontFamily: "Inter, sans-serif", fontSize: 15, color: "#A0A0A5" }}>{subtext}</span>
        ) : null}
      </div>
    </div>
  );
};
