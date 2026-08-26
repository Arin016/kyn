import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { KiroGlyph } from "../../src/components/KiroGlyph";

interface Props {
  mode: "intro" | "outro";
}

export const BrandCard: React.FC<Props> = ({ mode }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 90 } });
  const glyphScale = interpolate(enter, [0, 1], [0.72, 1]);
  const titleY = interpolate(enter, [0, 1], [28, 0]);
  const fade = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const subDelay = spring({ frame: Math.max(0, frame - 10), fps, config: { damping: 16 } });

  return (
    <AbsoluteFill
      style={{
        background: "#0A0A0A",
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
              opacity: spring({ frame: Math.max(0, frame - 18), fps, config: { damping: 18 } }),
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
    </AbsoluteFill>
  );
};
