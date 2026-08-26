import type { PermissionRequest, RunPhase, TimelineEntry } from "../../types";

const PHASE_COPY: Record<RunPhase, string> = {
  idle: "No run in progress",
  starting: "Starting",
  running: "Working",
  waiting: "Approval needed",
  stopping: "Stopping",
  error: "Error",
};

interface Props {
  phase: RunPhase;
  detail: string;
  permissions: PermissionRequest[];
  onDecide: (id: string, decision: "once" | "reject") => void;
  timeline: TimelineEntry[];
}

export function LiveTab({
  phase,
  detail,
  permissions,
  onDecide,
  timeline,
}: Props) {
  const anyPending = permissions.length > 0;

  return (
    <>
      <div className="run-card">
        <div className="run-card-top">
          <span className={`pulse-dot${phase === "running" || phase === "starting" ? " on" : ""}`} aria-hidden="true" />
          <span>{phase === "idle" ? "No run in progress" : PHASE_COPY[phase]}</span>
        </div>
        <p className="run-card-detail">{detail || "Tool activity and approval requests will appear here."}</p>
      </div>

      {anyPending && (
        <section aria-label="Permission requests" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <p className="section-label">Needs you</p>
          {permissions.map((permission) => (
            <article key={permission.id} className="approval-card">
              <p className="approval-title">{permission.title || "Tool permission requested"}</p>
              <p className="approval-context">
                {permission.toolName || "Tool action"}
                {permission.source ? ` · ${permission.source.replace("channel:", "")}` : ""}
              </p>
              <div className="approval-buttons">
                <button type="button" className="btn-approve" onClick={() => onDecide(permission.id, "once")}>
                  Allow once
                </button>
                <button type="button" className="btn-deny" onClick={() => onDecide(permission.id, "reject")}>
                  Deny
                </button>
              </div>
            </article>
          ))}
        </section>
      )}

      <section aria-label="Activity events">
        <p className="section-label">Timeline</p>
        {timeline.length === 0 ? (
          <p className="activity-empty">Phone chats, local turns, and approvals appear here as they happen.</p>
        ) : (
          <ol className="timeline">
            {timeline.map((entry) => (
              <li key={entry.id}>
                <span className="tl-time">{entry.at}</span>
                <span className={`tl-${entry.kind}`}>{entry.detail}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}
