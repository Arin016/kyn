import React from "react";
import { KiroGlyph } from "../src/components/KiroGlyph";
import { interpolate, springProgress, easeOutCubic } from "./motion";

export const DemoCursor: React.FC<{
  x: number;
  y: number;
  clicking?: boolean;
  visible?: boolean;
  clickAgeFrames?: number;
  fps?: number;
}> = ({ x, y, clicking = false, visible = true, clickAgeFrames = 0, fps = 30 }) => {
  if (!visible) return null;
  const press = clicking ? springProgress(clickAgeFrames / fps, fps) : 0;
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
      {clicking ? (
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
      ) : null}
    </div>
  );
};

export const DemoCaption: React.FC<{
  text: string;
  subtext?: string;
  frame: number;
  appearAt: number;
  fps?: number;
}> = ({ text, subtext, frame, appearAt, fps = 30 }) => {
  const enter = springProgress((frame - appearAt) / fps, fps);
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

export const DemoBrandCard: React.FC<{ mode: "intro" | "outro"; frame: number; localFrame: number }> = ({
  mode,
  frame,
  localFrame,
}) => {
  const enter = springProgress(localFrame / 30, 30);
  const glyphScale = interpolate(enter, [0, 1], [0.72, 1]);
  const titleY = interpolate(enter, [0, 1], [28, 0]);
  const fade = interpolate(frame, [0, 12], [0, 1]);
  const subDelay = springProgress(Math.max(0, localFrame - 10) / 30, 30);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "#0A0A0A",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        opacity: fade,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse 70% 50% at 50% 42%, rgba(176,139,255,0.16), transparent 70%)",
        }}
      />
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 22,
          transform: `translateY(${titleY}px)`,
          zIndex: 1,
        }}
      >
        <div style={{ transform: `scale(${glyphScale})` }}>
          <KiroGlyph size={96} title="KYN" />
        </div>
        <div style={{ textAlign: "center" }}>
          <h1
            style={{
              margin: 0,
              fontFamily: '"Space Grotesk Variable", "Space Grotesk", Inter, sans-serif',
              fontSize: mode === "intro" ? 72 : 56,
              fontWeight: 650,
              letterSpacing: "-0.05em",
              color: "#FFFFFF",
            }}
          >
            KYN
          </h1>
          <p
            style={{
              margin: "14px 0 0",
              fontFamily: "Inter, sans-serif",
              fontSize: 22,
              color: "#D4D4D8",
              opacity: subDelay,
              maxWidth: 640,
              lineHeight: 1.45,
            }}
          >
            {mode === "intro"
              ? "Beyond the terminal."
              : "Persistent agents. Phone continuity. Approvals you can trust."}
          </p>
        </div>
        {mode === "outro" ? (
          <div
            style={{
              marginTop: 8,
              opacity: springProgress(Math.max(0, localFrame - 18) / 30, 30),
              padding: "10px 18px",
              borderRadius: 999,
              border: "1px solid rgba(176,139,255,0.4)",
              color: "#B08BFF",
              fontFamily: "Inter, sans-serif",
              fontSize: 15,
              fontWeight: 600,
            }}
          >
            Local control plane · open the studio to iterate
          </div>
        ) : null}
      </div>
    </div>
  );
};

export const DemoHighlight: React.FC<{
  x: number;
  y: number;
  width: number;
  height: number;
  label?: string;
}> = ({ x, y, width, height, label }) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      width,
      height,
      borderRadius: 12,
      border: "2px solid rgba(176,139,255,0.55)",
      boxShadow: "0 0 0 4px rgba(176,139,255,0.12)",
      zIndex: 800,
      pointerEvents: "none",
    }}
  >
    {label ? (
      <span
        style={{
          position: "absolute",
          top: -28,
          left: 0,
          fontFamily: "Inter, sans-serif",
          fontSize: 13,
          fontWeight: 600,
          color: "#B08BFF",
        }}
      >
        {label}
      </span>
    ) : null}
  </div>
);

export const DemoCamera: React.FC<{
  scale: number;
  x: number;
  y: number;
  children: React.ReactNode;
}> = ({ scale, x, y, children }) => {
  const s = Math.max(0.7, scale);
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        transform: `translate(${x}px, ${y}px) scale(${s})`,
        transformOrigin: "50% 50%",
        willChange: "transform",
      }}
    >
      {children}
    </div>
  );
};

export function easeCamera(
  frame: number,
  from: { scale: number; x: number; y: number },
  to: { scale: number; x: number; y: number },
  start: number,
  end: number,
) {
  const t = interpolate(frame, [start, end], [0, 1], easeOutCubic);
  return {
    scale: from.scale + (to.scale - from.scale) * t,
    x: from.x + (to.x - from.x) * t,
    y: from.y + (to.y - from.y) * t,
  };
}
