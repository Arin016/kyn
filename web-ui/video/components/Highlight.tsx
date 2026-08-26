import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

interface Props {
  x: number;
  y: number;
  width: number;
  height: number;
  active: boolean;
  label?: string;
}

export const Highlight: React.FC<Props> = ({ x, y, width, height, active, label }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!active) return null;

  const pulse = spring({
    frame: frame % 45,
    fps,
    config: { damping: 12, stiffness: 90 },
  });
  const glow = interpolate(pulse, [0, 1], [0.35, 0.85]);

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        height,
        borderRadius: 14,
        border: "2px solid rgba(176,139,255,0.9)",
        boxShadow: `0 0 0 6px rgba(176,139,255,${0.12 * glow}), 0 0 28px rgba(176,139,255,${0.35 * glow})`,
        zIndex: 850,
        pointerEvents: "none",
      }}
    >
      {label ? (
        <span
          style={{
            position: "absolute",
            top: -28,
            left: 0,
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            color: "#B08BFF",
            fontFamily: "Inter, sans-serif",
          }}
        >
          {label}
        </span>
      ) : null}
    </div>
  );
};
