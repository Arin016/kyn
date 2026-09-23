import type { PermissionRequest, RunPhase, TimelineEntry } from "../../types";
import { Badge } from "../ui/Basics";

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
  const live = phase === "running" || phase === "starting" || phase === "waiting" || phase === "stopping";

  const counts = timeline.reduce<Record<string, number>>((tally, entry) => {
    tally[entry.kind] = (tally[entry.kind] || 0) + 1;
    return tally;
  }, {});

  return (
    <>
      <div className={`run-card${live ? " is-live" : ""}`}>
        <div className="run-card-top">
          <span className={`pulse-dot${phase === "running" || phase === "starting" ? " on" : ""}`} aria-hidden="true" />
          <span>{phase === "idle" ? "No run in progress" : PHASE_COPY[phase]}</span>
          {live ? <span className="run-card__elapsed">live</span> : null}
        </div>
        <p className="run-card-detail">{detail || "Tool activity and approval requests will appear here."}</p>
        {timeline.length > 0 && (
          <div className="timeline-tally">
            {Object.entries(counts).map(([kind, count]) => (
              <span key={kind} className={`tl-chip tl-${kind}`}>
                {count} {kind}
              </span>
            ))}
          </div>
        )}
      </div>

      {anyPending && (
        <section className="panel-section" aria-label="Permission requests">
          <div className="panel-section-head">
            <div>
              <p className="section-label">Needs you</p>
              <p className="section-hint">Nothing continues until you decide.</p>
            </div>
            <Badge tone="warning" dot>
              {permissions.length} waiting
            </Badge>
          </div>
          {permissions.map((permission) => (
            <article key={permission.id} className="approval-card">
              <p className="approval-title">{permission.title || "Tool permission requested"}</p>
              <div className="approval-facts">
                <code className="approval-tool">{permission.toolName || "Tool action"}</code>
                {permission.source ? <span className="work-chip">{permission.source.replace("channel:", "")}</span> : null}
              </div>
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

      <section className="panel-section" aria-label="Activity events">
        <p className="section-label">Timeline</p>
        {timeline.length === 0 ? (
          <p className="activity-empty">Phone chats, local turns, and approvals appear here as they happen.</p>
        ) : (
          <ol className="timeline">
            {[...timeline].reverse().map((entry) => (
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
