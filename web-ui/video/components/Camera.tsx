import React from "react";
import { AbsoluteFill, interpolate } from "remotion";

interface Props {
  scale: number;
  x: number;
  y: number;
  children: React.ReactNode;
}

/** Cinematic camera: scale around a focal point expressed in composition coords. */
export const Camera: React.FC<Props> = ({ scale, x, y, children }) => {
  const s = Math.max(0.7, scale);
  return (
    <AbsoluteFill
      style={{
        transform: `translate(${x}px, ${y}px) scale(${s})`,
        transformOrigin: "50% 50%",
        willChange: "transform",
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

export function easeCamera(
  frame: number,
  from: { scale: number; x: number; y: number },
  to: { scale: number; x: number; y: number },
  start: number,
  end: number,
) {
  const t = interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: (v) => 1 - Math.pow(1 - v, 3),
  });
  return {
    scale: from.scale + (to.scale - from.scale) * t,
    x: from.x + (to.x - from.x) * t,
    y: from.y + (to.y - from.y) * t,
  };
}
