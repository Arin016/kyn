import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type {
  Channel,
  ChannelEvent,
  CodingExecution,
  DelegationPlan,
  Routine,
} from "../../types";
import { fullTime, shortTime, truncate } from "../../lib/format";
import { EmptyState, Badge } from "../ui/Basics";
import { SegmentedControl, ToggleSwitch } from "../ui/Pickers";
import type { Option } from "../ui/Pickers";

export interface WorkActions {
  onNewRoutine: () => void;
  onToggleRoutine: (routine: Routine) => void;
  onDeleteRoutine: (routine: Routine) => void;
  onNewCoding: () => void;
  onApproveCoding: (execution: CodingExecution) => void;
  onCancelCoding: (execution: CodingExecution) => void;
  onNewDelegation: () => void;
  onStartDelegation: (plan: DelegationPlan) => void;
  onCancelDelegation: (plan: DelegationPlan) => void;
  onNewChannel: () => void;
  onCopyWebhook: (channel: Channel) => void;
  onToggleChannel: (channel: Channel) => void;
  onDeleteChannel: (channel: Channel) => void;
}

interface Props {
  routines: Routine[];
  codingExecutions: CodingExecution[];
  delegations: DelegationPlan[];
  channels: Channel[];
  channelEvents: ChannelEvent[];
  actions: WorkActions;
}

const CHANNEL_GLYPH: Record<string, string> = {
  telegram: "TG",
  slack: "SL",
  github: "GH",
  whatsapp: "WA",
  email: "@",
  webhook: "/",
};

const CODING_STAGES = ["building", "verifying", "awaiting handoff", "ready"];

const FILTERS: Option<string>[] = [
  { value: "all", label: "All" },
  { value: "live", label: "Live" },
  { value: "paused", label: "Paused" },
  { value: "done", label: "Finished" },
];

function relative(value?: string): string {
  if (!value) return "";
  const target = new Date(value).getTime();
  if (Number.isNaN(target)) return "";
  const delta = Math.round((target - Date.now()) / 1000);
  const abs = Math.abs(delta);
  const unit =
    abs < 60
      ? `${abs}s`
      : abs < 3600
        ? `${Math.round(abs / 60)}m`
        : `${Math.round(abs / 3600)}h`;
  return delta >= 0 ? `in ${unit}` : `${unit} ago`;
}

function cadence(routine: Routine): string {
  if (routine.trigger_kind === "once")
    return `Once · ${fullTime(routine.run_at)}`;
  const seconds = routine.interval_seconds || 0;
  if (seconds < 3600)
    return `Every ${Math.max(1, Math.round(seconds / 60))} min`;
  const hours = Math.round(seconds / 360) / 10;
  return `Every ${hours}h`;
}

function StageTrack({ stage }: { stage: string }) {
  const current = CODING_STAGES.indexOf(stage);
  const failed = ["failed", "cancelled"].includes(stage);
  return (
    <ol
      className="stage-track"
      aria-label={`Stage: ${stage.replaceAll("_", " ")}`}
    >
      {CODING_STAGES.map((item, index) => (
        <li
          key={item}
          className="stage-step"
          data-state={
            failed
              ? "failed"
              : current === index
                ? "current"
                : current > index
                  ? "done"
                  : "todo"
          }
          title={item}
        >
          <span className="stage-dot" aria-hidden />
          <span className="stage-name">
            {item === "awaiting handoff" ? "handoff" : item}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Section({
  title,
  hint,
  count,
  action,
  children,
}: {
  title: string;
  hint: string;
  count?: number;
  action?: { label: string; onClick: () => void };
  children: ReactNode;
}) {
  return (
    <section className="panel-section" aria-label={title}>
      <div className="panel-section-head">
        <div>
          <p className="section-label">
            {title}
            {typeof count === "number" && count > 0 ? (
              <span className="section-count">{count}</span>
            ) : null}
          </p>
          <p className="section-hint">{hint}</p>
        </div>
        {action ? (
          <button
            type="button"
            className="mini-primary"
            onClick={action.onClick}
          >
            {action.label}
          </button>
        ) : null}
      </div>
      {children}
    </section>
  );
}

export function WorkTab({
  routines,
  codingExecutions,
  delegations,
  channels,
  channelEvents,
  actions,
}: Props) {
  const [filter, setFilter] = useState("all");
  const [openReplies, setOpenReplies] = useState<string[]>([]);

  const bindingIds = new Set(channels.map((channel) => channel.id));
  const recentRemote = channelEvents
    .filter((event) => bindingIds.has(event.binding_id))
    .slice(0, 12);

  const matches = (state: "live" | "paused" | "done") => {
    if (filter === "all") return true;
    if (filter === "live") return state === "live";
    if (filter === "paused") return state === "paused";
    return state === "done";
  };

  const visibleRoutines = routines.filter((routine) =>
    matches(routine.enabled ? "live" : "paused"),
  );
  const visibleCoding = codingExecutions.filter((execution) =>
    ["failed", "cancelled", "ready"].includes(execution.status)
      ? matches("done")
      : matches("live"),
  );
  const visiblePlans = delegations.filter((plan) =>
    ["succeeded", "failed", "cancelled"].includes(plan.status)
      ? matches("done")
      : plan.status === "paused"
        ? matches("paused")
        : matches("live"),
  );
  const visibleChannels = channels.filter((channel) =>
    matches(channel.enabled ? "live" : "paused"),
  );

  return (
    <>
      <div className="work-filter">
        <SegmentedControl
          value={filter}
          options={FILTERS}
          onChange={setFilter}
          label="Filter work"
          size="sm"
        />
        <span className="work-filter-count">
          {routines.length +
            codingExecutions.length +
            delegations.length +
            channels.length}{" "}
          items
        </span>
      </div>

      <Section
        title="Scheduled work"
        hint="Recurring prompts for this bot. Pause anything without losing the schedule."
        count={routines.length}
        action={{ label: "New routine", onClick: actions.onNewRoutine }}
      >
        <div className="work-cards">
          {visibleRoutines.length === 0 && (
            <EmptyState>
              {routines.length === 0
                ? "No routines yet."
                : "Nothing matches this filter."}
            </EmptyState>
          )}
          {visibleRoutines.map((routine) => (
            <article
              key={routine.id}
              className="work-card"
              data-state={routine.enabled ? "live" : "paused"}
            >
              <div className="work-card-head">
                <div className="work-card-title">
                  <strong>{routine.name}</strong>
                  <span className="work-chip">{cadence(routine)}</span>
                </div>
                <ToggleSwitch
                  label={routine.enabled ? "Active" : "Paused"}
                  checked={routine.enabled}
                  onChange={() => actions.onToggleRoutine(routine)}
                />
              </div>
              <p className="work-card-meta">
                {routine.next_run_at ? (
                  <>
                    Next run <strong>{fullTime(routine.next_run_at)}</strong> ·{" "}
                    {relative(routine.next_run_at)}
                  </>
                ) : (
                  "Not scheduled"
                )}
              </p>
              <div className="work-card-actions">
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => actions.onToggleRoutine(routine)}
                >
                  {routine.enabled ? "Pause" : "Resume"}
                </button>
                <button
                  type="button"
                  className="link-btn link-btn--danger"
                  onClick={() => actions.onDeleteRoutine(routine)}
                >
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      </Section>

      <Section
        title="Coding executions"
        hint="Build, verify, repair and review a task in an isolated worktree."
        count={codingExecutions.length}
        action={{ label: "New execution", onClick: actions.onNewCoding }}
      >
        <div className="work-cards">
          {visibleCoding.length === 0 && (
            <EmptyState>
              {codingExecutions.length === 0
                ? "No coding executions yet."
                : "Nothing matches this filter."}
            </EmptyState>
          )}
          {visibleCoding.map((execution) => {
            const spec = execution.spec || {};
            const repairs = execution.result?.repair_attempts_used ?? 0;
            const terminal = ["failed", "cancelled"].includes(execution.status);
            const canCancel = !["ready", "failed", "cancelled"].includes(
              execution.status,
            );
            return (
              <article
                key={execution.id}
                className="work-card"
                data-state={terminal ? "done" : "live"}
              >
                <div className="work-card-head">
                  <div className="work-card-title">
                    <strong>
                      {truncate(spec.task || "Coding execution", 70)}
                    </strong>
                  </div>
                  <Badge
                    tone={
                      execution.status === "ready"
                        ? "success"
                        : terminal
                          ? "danger"
                          : execution.status === "awaiting_handoff"
                            ? "warning"
                            : "accent"
                    }
                    dot
                  >
                    {String(execution.status || "queued").replaceAll("_", " ")}
                  </Badge>
                </div>
                <StageTrack stage={String(execution.status || "queued")} />
                <div className="work-card-facts">
                  <span className="work-chip">
                    {spec.builder_bot || "builder"} →{" "}
                    {spec.reviewer_bot || "reviewer"}
                  </span>
                  <span className="work-chip">
                    {repairs} repair{repairs === 1 ? "" : "s"}
                  </span>
                  <span className="work-chip">
                    {(spec.checks || []).length || 0} checks
                  </span>
                  {spec.repo_path ? (
                    <span className="work-chip">
                      {truncate(spec.repo_path, 28)}
                    </span>
                  ) : null}
                </div>
                <div className="work-card-actions">
                  {execution.status === "awaiting_handoff" && (
                    <button
                      type="button"
                      className="link-btn link-btn--primary"
                      onClick={() => actions.onApproveCoding(execution)}
                    >
                      Approve handoff
                    </button>
                  )}
                  {canCancel && (
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => actions.onCancelCoding(execution)}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </Section>

      <Section
        title="Team plans"
        hint="Coordinate several bots on one goal, with dependencies between steps."
        count={delegations.length}
        action={{ label: "Open canvas", onClick: actions.onNewDelegation }}
      >
        <div className="work-cards">
          {visiblePlans.length === 0 && (
            <EmptyState>
              {delegations.length === 0
                ? "No team plans yet."
                : "Nothing matches this filter."}
            </EmptyState>
          )}
          {[...visiblePlans].reverse().map((plan) => {
            const terminal = ["succeeded", "failed", "cancelled"].includes(
              plan.status,
            );
            return (
              <article
                key={plan.id}
                className="work-card"
                data-state={
                  terminal
                    ? "done"
                    : plan.status === "paused"
                      ? "paused"
                      : "live"
                }
              >
                <div className="work-card-head">
                  <div className="work-card-title">
                    <strong>{plan.name}</strong>
                  </div>
                  <Badge
                    tone={
                      plan.status === "succeeded"
                        ? "success"
                        : terminal
                          ? "danger"
                          : plan.status === "paused"
                            ? "muted"
                            : "accent"
                    }
                    dot
                  >
                    {plan.status.replaceAll("_", " ")}
                  </Badge>
                </div>
                <div className="work-card-facts">
                  <span className="work-chip">
                    fan-out {plan.max_fanout ?? 1}
                  </span>
                  <span className="work-chip">depth {plan.max_depth ?? 1}</span>
                  {plan.created_at ? (
                    <span className="work-chip">
                      {relative(plan.created_at)}
                    </span>
                  ) : null}
                </div>
                <div className="work-card-actions">
                  {plan.status === "paused" && (
                    <button
                      type="button"
                      className="link-btn link-btn--primary"
                      onClick={() => actions.onStartDelegation(plan)}
                    >
                      Start plan
                    </button>
                  )}
                  {!terminal && (
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => actions.onCancelDelegation(plan)}
                    >
                      Cancel plan
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </Section>

      <Section
        title="Remote channels"
        hint="Talk to this bot from Telegram, Slack, GitHub, WhatsApp or a webhook."
        count={channels.length}
        action={{ label: "Connect", onClick: actions.onNewChannel }}
      >
        <div className="work-cards">
          {visibleChannels.length === 0 && (
            <EmptyState>
              {channels.length === 0
                ? "No remote channels yet."
                : "Nothing matches this filter."}
            </EmptyState>
          )}
          {visibleChannels.map((channel) => {
            const polling = channel.kind === "telegram";
            return (
              <article
                key={channel.id}
                className="work-card"
                data-state={channel.enabled ? "live" : "paused"}
              >
                <div className="work-card-head">
                  <div className="work-card-title">
                    <span
                      className={`channel-glyph${channel.enabled ? " is-live" : ""}`}
                      aria-hidden
                    >
                      {CHANNEL_GLYPH[channel.kind] || "··"}
                    </span>
                    <strong>{channel.name}</strong>
                    <span className="work-chip">{channel.kind}</span>
                  </div>
                  <ToggleSwitch
                    label={channel.enabled ? "Live" : "Paused"}
                    checked={channel.enabled}
                    onChange={() => actions.onToggleChannel(channel)}
                  />
                </div>
                <p className="work-card-meta">
                  {channel.outbound_delivery_configured
                    ? "Replies are delivered back"
                    : "Replies stored in this console"}
                </p>
                <code className="work-card-path">
                  {polling
                    ? "Laptop polls Telegram · no public URL"
                    : `/hooks/${channel.kind}/${channel.id}`}
                </code>
                <div className="work-card-actions">
                  {!polling && (
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => actions.onCopyWebhook(channel)}
                    >
                      Copy webhook URL
                    </button>
                  )}
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => actions.onToggleChannel(channel)}
                  >
                    {channel.enabled ? "Pause" : "Resume"}
                  </button>
                  <button
                    type="button"
                    className="link-btn link-btn--danger"
                    onClick={() => actions.onDeleteChannel(channel)}
                  >
                    Delete
                  </button>
                </div>
              </article>
            );
          })}
        </div>

        <p className="section-label spaced">Recent remote requests</p>
        <div className="work-cards">
          {recentRemote.length === 0 && (
            <EmptyState>No remote requests yet.</EmptyState>
          )}
          {recentRemote.map((event) => {
            const open = openReplies.includes(event.id);
            return (
              <article key={event.id} className="work-card work-card--compact">
                <div className="work-card-head">
                  <div className="work-card-title">
                    <strong>
                      {truncate(event.text || "Remote request", 70)}
                    </strong>
                  </div>
                  <Badge
                    tone={
                      ["failed", "cancelled"].includes(event.status)
                        ? "danger"
                        : ["responded", "stored"].includes(event.status)
                          ? "success"
                          : "accent"
                    }
                    dot
                  >
                    {event.status}
                  </Badge>
                </div>
                <div className="work-card-facts">
                  <span className="work-chip">
                    {event.sender || "unknown sender"}
                  </span>
                  <span className="work-chip">{event.source || "remote"}</span>
                  {event.created_at ? (
                    <span className="work-chip">
                      {shortTime(event.created_at)}
                    </span>
                  ) : null}
                </div>
                {(event.response_text || event.error) && (
                  <button
                    type="button"
                    className="reply-disclosure"
                    aria-expanded={open}
                    onClick={() =>
                      setOpenReplies((current) =>
                        current.includes(event.id)
                          ? current.filter((id) => id !== event.id)
                          : [...current, event.id],
                      )
                    }
                  >
                    {open ? "Hide reply" : "Show reply"}
                  </button>
                )}
                {open && (
                  <p className="work-card-reply">
                    {event.response_text || event.error}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </Section>
    </>
  );
}

/** Keeps the panel in sync with the daemon clock for relative times. */
export function useTicker(intervalMs = 30_000): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(
      () => setTick((value) => value + 1),
      intervalMs,
    );
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return tick;
}
