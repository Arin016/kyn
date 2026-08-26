import React from "react";
import { REVIEWER_OUTPUT } from "../timeline";
import { Sidebar } from "../../src/components/Sidebar";
import { KiroGlyph } from "../../src/components/KiroGlyph";
import type { WorkflowSnapshot } from "../workflowState";
import { workflowEdgePath, WORKFLOW_BOARD } from "../workflowState";
import { scenes } from "../timeline";

const BOTS = [
  { name: "builder", cwd: "/Users/arin.mallanna/personal", model: "Kiro" },
  { name: "reviewer", cwd: "/Users/arin.mallanna/personal", model: "Kiro" },
  { name: "triage", cwd: "/Users/arin.mallanna/personal/kyn", agent: "triage" },
];

const noop = () => undefined;

interface Props {
  snapshot: WorkflowSnapshot;
  frame: number;
  fps: number;
}

function statusClass(status?: string): string {
  if (status === "running" || status === "pending") return "running";
  if (status === "succeeded") return "succeeded";
  if (status === "failed") return "failed";
  return "paused";
}

export const DemoWorkflowPage: React.FC<Props> = ({ snapshot, frame, fps }) => {

  const plans = snapshot.planStatus !== "draft"
    ? [
        {
          id: "plan-ship",
          name: snapshot.name || "Ship the release safely",
          status: snapshot.planStatus,
          max_fanout: 2,
          max_depth: 3,
        },
      ]
    : [];

  return (
    <div className="app demo-console">
      <Sidebar
        bots={BOTS}
        selectedBot="builder"
        onSelectBot={noop}
        channels={[]}
        channelEvents={[]}
        surface={{ kind: "local" }}
        onSelectSurface={noop}
        unread={{}}
        localLive={snapshot.planStatus === "running"}
        connected
        open
        theme="dark"
        onToggleTheme={noop}
        onNewBot={noop}
        workspace="workflows"
        onWorkspaceChange={noop}
      />

      <section className="workflow-page" aria-label="Workflow playground">
        <aside className="workflow-rail" aria-label="Workflows">
          <div className="workflow-rail-header">
            <div>
              <p className="eyebrow">Control room</p>
              <h2>Workflows</h2>
            </div>
            <button type="button" className="workflow-new">＋ New</button>
          </div>
          <p className="workflow-rail-copy">
            Compose agents, watch their state, and inspect each bot&apos;s output in one place.
          </p>
          <div className="workflow-list" role="list">
            <button type="button" className="workflow-list-item draft">
              <span className="workflow-list-symbol">＋</span>
              <span>
                <strong>Untitled workflow</strong>
                <small>New editable canvas</small>
              </span>
            </button>
            {plans.map((plan) => (
              <button
                key={plan.id}
                type="button"
                className="workflow-list-item selected"
              >
                <span className={`workflow-plan-dot ${plan.status}`} />
                <span>
                  <strong>{plan.name}</strong>
                  <small>
                    {plan.status.replaceAll("_", " ")} · {plan.max_fanout} parallel · depth {plan.max_depth}
                  </small>
                </span>
              </button>
            ))}
          </div>
          <button type="button" className="workflow-back">← Back to conversation</button>
        </aside>

        <div className="workflow-stage">
          <header className="workflow-stage-header">
            <div className="header-brand" style={{ gap: 10 }}>
              <span className="header-logo" aria-hidden>
                <KiroGlyph size={20} />
              </span>
              <div>
                <p className="eyebrow">{snapshot.planStatus === "draft" ? "New workflow" : "Saved workflow"}</p>
                <h1>{snapshot.name || "Build a team"}</h1>
              </div>
            </div>
            <div className="workflow-stage-state">{snapshot.statusLine}</div>
          </header>

          <section className="flow-studio" aria-label="Workflow canvas">
            <div className="flow-toolbar">
              <label className="flow-name">
                <span>Workflow</span>
                <input
                  value={snapshot.name}
                  readOnly
                  placeholder="Ship the release safely"
                />
              </label>
              <div className="flow-tool-group">
                <button type="button" className="flow-tool primary">＋ Bot</button>
                <button type="button" className="flow-tool">Auto layout</button>
                <span className="flow-zoom">{Math.round(snapshot.zoom * 100)}%</span>
              </div>
              <button
                type="button"
                className="flow-run"
                style={
                  snapshot.runHot
                    ? { boxShadow: "0 0 0 4px rgba(176,139,255,0.45)", transform: "scale(1.03)" }
                    : undefined
                }
              >
                {snapshot.planStatus === "running" ? "Running…" : "Run workflow"}
              </button>
            </div>

            <div className="flow-hint">
              <span className="flow-live-dot" />
              {snapshot.notice}
              {snapshot.connectingFrom ? <strong> Choose the next bot…</strong> : null}
            </div>

            <div className="flow-viewport">
              <div
                className="flow-scale"
                style={{
                  width: WORKFLOW_BOARD.width * snapshot.zoom,
                  height: WORKFLOW_BOARD.height * snapshot.zoom,
                }}
              >
                <div
                  className="flow-canvas"
                  style={{
                    width: WORKFLOW_BOARD.width,
                    height: WORKFLOW_BOARD.height,
                    transform: `scale(${snapshot.zoom})`,
                  }}
                >
                  <svg
                    className="flow-edges"
                    width={WORKFLOW_BOARD.width}
                    height={WORKFLOW_BOARD.height}
                    aria-hidden="true"
                  >
                    <defs>
                      <marker
                        id="flow-arrow-demo"
                        viewBox="0 0 10 10"
                        refX="9"
                        refY="5"
                        markerWidth="7"
                        markerHeight="7"
                        orient="auto-start-reverse"
                      >
                        <path d="M 0 0 L 10 5 L 0 10 z" />
                      </marker>
                    </defs>
                    {snapshot.edges.map((edge) => {
                      const d = workflowEdgePath(edge.sourceId, edge.targetId, snapshot.nodes);
                      if (!d || edge.drawProgress <= 0) return null;
                      return (
                        <path
                          key={`${edge.sourceId}:${edge.targetId}`}
                          d={d}
                          markerEnd="url(#flow-arrow-demo)"
                          strokeDasharray="1000"
                          strokeDashoffset={1000 - edge.drawProgress * 1000}
                        />
                      );
                    })}
                  </svg>

                  {snapshot.nodes.map((node) => {
                    const n3Start = scenes.workflow.start + Math.round(2.5 * fps);
                    const enterFrames = node.id === "wf-n3" ? Math.max(0, frame - n3Start) : 0;
                    const enter = node.id === "wf-n3" ? Math.min(1, enterFrames / (fps * 0.5)) : 1;
                    const opacity = enter;
                    const scale = node.id === "wf-n3" ? 0.92 + 0.08 * enter : 1;
                    const selected = snapshot.selectedNodeId === node.id;

                    return (
                      <article
                        key={node.id}
                        className={`flow-node${selected ? " dragging" : ""}`}
                        style={{
                          left: node.x,
                          top: node.y,
                          width: WORKFLOW_BOARD.nodeW,
                          minHeight: WORKFLOW_BOARD.nodeH,
                          opacity,
                          transform: `scale(${scale})`,
                          borderColor: selected ? "rgba(176,139,255,0.55)" : undefined,
                        }}
                      >
                        <button
                          type="button"
                          className={`flow-port input${snapshot.connectTargetReady && node.id === "wf-n3" ? " ready" : ""}`}
                          aria-hidden
                        />
                        <header className="flow-node-header">
                          <span className="flow-node-index">{String(node.index).padStart(2, "0")}</span>
                          <span className="flow-node-kind">KYN bot</span>
                          <span className="flow-node-grip" aria-hidden>⠿</span>
                          {node.status === "running" ? (
                            <span
                              className={`workflow-plan-dot ${statusClass(node.status)}`}
                              style={{ marginRight: 4 }}
                            />
                          ) : null}
                        </header>
                        <div className="flow-node-body">
                          <label>
                            <span>Agent</span>
                            <select value={node.botName} disabled>
                              <option>{node.botName}</option>
                            </select>
                          </label>
                          <label>
                            <span>Instruction</span>
                            <textarea value={node.prompt} readOnly rows={4} />
                          </label>
                          <div className="flow-node-meta">
                            {node.after.length
                              ? `Waits for ${node.after.length} node${node.after.length === 1 ? "" : "s"}`
                              : "Runs immediately"}
                            {node.status === "succeeded" ? " · done" : ""}
                            {node.status === "running" ? " · working" : ""}
                          </div>
                        </div>
                        <button
                          type="button"
                          className={`flow-port output${snapshot.connectingFrom === node.id ? " active" : ""}`}
                          aria-hidden
                        />
                      </article>
                    );
                  })}
                </div>
              </div>
            </div>

            <footer className="flow-footer">
              <div className="flow-status-copy">
                <span className="flow-status-badge">Canvas event</span>
                <p>{snapshot.notice}</p>
              </div>
              {snapshot.showReviewerOutput ? (
                <div className="flow-output">
                  <strong>reviewer</strong>
                  <span>succeeded</span>
                  <p>{snapshot.selectedNodeId ? undefined : ""}</p>
                  <p style={{ marginTop: 4 }}>{REVIEWER_OUTPUT}</p>
                </div>
              ) : (
                <div className="flow-summary">
                  <strong>{snapshot.nodes.length}</strong> bots · <strong>{snapshot.edges.length}</strong> arrows ·
                  roots run in parallel
                </div>
              )}
            </footer>
          </section>
        </div>
      </section>
    </div>
  );
};
