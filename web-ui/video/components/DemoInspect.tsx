import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { LiveTab } from "../../src/components/inspect/LiveTab";
import type { PermissionRequest, RunPhase, TimelineEntry } from "../../src/types";

interface Props {
  open: boolean;
  openedAt: number;
  phase: RunPhase;
  runDetail: string;
  permissions: PermissionRequest[];
  timeline: TimelineEntry[];
  approveHot?: boolean;
}

export const DemoInspect: React.FC<Props> = ({
  open,
  openedAt,
  phase,
  runDetail,
  permissions,
  timeline,
  approveHot = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const localFrame = open ? Math.max(0, frame - openedAt) : 0;

  const slide = spring({
    frame: localFrame,
    fps,
    config: { damping: 18, stiffness: 140, mass: 0.7 },
  });
  const x = open ? interpolate(slide, [0, 1], [340, 0]) : 340;
  const opacity = open ? interpolate(slide, [0, 1], [0, 1]) : 0;

  if (!open && opacity < 0.01) return null;

  return (
    <aside
      className="inspect"
      aria-label="Inspect"
      data-demo-inspect
      style={{
        transform: `translateX(${x}px)`,
        opacity,
        display: "flex",
      }}
    >
      <div className="inspect-header">
        <div>
          <p className="eyebrow" style={{ margin: 0, color: "var(--fg-faint)", fontSize: 12 }}>
            Inspect
          </p>
          <h2 style={{ margin: "2px 0 0", fontSize: 16 }}>Activity · builder</h2>
        </div>
        <button type="button" className="icon-btn" aria-label="Close">
          Close
        </button>
      </div>
      <nav className="panel-tabs" aria-label="Inspect views">
        <button type="button" className="panel-tab" aria-selected>
          Live
        </button>
        <button type="button" className="panel-tab">
          Work
        </button>
        <button type="button" className="panel-tab">
          Safety
        </button>
        <button type="button" className="panel-tab">
          Memory
        </button>
      </nav>
      <div style={{ overflow: "auto", paddingBottom: 16 }} data-approve-hot={approveHot ? "1" : "0"}>
        <LiveTab
          phase={phase}
          detail={runDetail}
          permissions={permissions}
          onDecide={() => undefined}
          timeline={timeline}
        />
      </div>
      {approveHot && permissions.length > 0 ? (
        <div
          style={{
            position: "absolute",
            left: 24,
            top: 210,
            width: 118,
            height: 36,
            borderRadius: 999,
            boxShadow: "0 0 0 3px rgba(176,139,255,0.55)",
            pointerEvents: "none",
          }}
        />
      ) : null}
    </aside>
  );
};
