import type { Channel, ChannelEvent, CodingExecution, DelegationPlan, Routine } from "../../types";
import { fullTime, truncate } from "../../lib/format";
import { ActionLink, ManagementCard } from "./ManagementCard";
import { EmptyState } from "../ui/Basics";

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

export function WorkTab({ routines, codingExecutions, delegations, channels, channelEvents, actions }: Props) {
  const bindingIds = new Set(channels.map((channel) => channel.id));
  const recentRemote = channelEvents.filter((event) => bindingIds.has(event.binding_id)).slice(0, 12);

  return (
    <>
      <div className="panel-action-row">
        <p>Scheduled work for this bot.</p>
        <button type="button" className="mini-primary" onClick={actions.onNewRoutine}>
          Add
        </button>
      </div>
      <div className="management-list">
        {routines.length === 0 && <EmptyState>No routines yet.</EmptyState>}
        {routines.map((routine) => {
          const schedule =
            routine.trigger_kind === "once"
              ? `Once · ${fullTime(routine.run_at)}`
              : `Every ${Math.round((routine.interval_seconds || 0) / 60)} min`;
          return (
            <ManagementCard
              key={routine.id}
              title={routine.name}
              meta={`${schedule}\nNext: ${routine.next_run_at ? fullTime(routine.next_run_at) : "not scheduled"}`}
              badge={routine.enabled ? "active" : "paused"}
              enabled={routine.enabled}
              actions={
                <>
                  <ActionLink onClick={() => actions.onToggleRoutine(routine)}>
                    {routine.enabled ? "Pause" : "Resume"}
                  </ActionLink>
                  <ActionLink onClick={() => actions.onDeleteRoutine(routine)}>Delete</ActionLink>
                </>
              }
            />
          );
        })}
      </div>

      <section className="connections-section">
        <div className="panel-action-row">
          <p>Build, verify, repair, and review in an isolated worktree.</p>
          <button type="button" className="mini-primary" onClick={actions.onNewCoding}>
            Add
          </button>
        </div>
        <div className="management-list">
          {codingExecutions.length === 0 && <EmptyState>No coding executions yet.</EmptyState>}
          {codingExecutions.map((execution) => {
            const spec = execution.spec || {};
            const repairs = execution.result?.repair_attempts_used ?? 0;
            const status = String(execution.status || "queued").replaceAll("_", " ");
            const terminal = ["failed", "cancelled"].includes(execution.status);
            const canCancel = !["ready", "failed", "cancelled"].includes(execution.status);
            return (
              <ManagementCard
                key={execution.id}
                title={truncate(spec.task || "Coding execution", 64)}
                meta={`${spec.builder_bot || "builder"} → ${spec.reviewer_bot || "reviewer"} · ${repairs} repair(s)`}
                badge={status}
                badgeTone={
                  execution.status === "ready"
                    ? "success"
                    : terminal
                      ? "muted"
                      : execution.status === "awaiting_handoff"
                        ? "warning"
                        : "accent"
                }
                enabled={!terminal}
                actions={
                  <>
                    {execution.status === "awaiting_handoff" && (
                      <ActionLink onClick={() => actions.onApproveCoding(execution)}>Approve handoff</ActionLink>
                    )}
                    {canCancel && <ActionLink onClick={() => actions.onCancelCoding(execution)}>Cancel</ActionLink>}
                  </>
                }
              />
            );
          })}
        </div>
      </section>

      <section className="connections-section">
        <div className="panel-action-row">
          <p>Coordinate several bots on one goal.</p>
          <button type="button" className="mini-primary" onClick={actions.onNewDelegation}>
            Open canvas
          </button>
        </div>
        <div className="management-list">
          {delegations.length === 0 && <EmptyState>No team plans yet.</EmptyState>}
          {[...delegations].reverse().map((plan) => {
            const terminal = ["succeeded", "failed", "cancelled"].includes(plan.status);
            return (
              <ManagementCard
                key={plan.id}
                title={plan.name}
                meta={`Up to ${plan.max_fanout ?? 1} bots in parallel · depth ${plan.max_depth ?? 1}`}
                badge={plan.status.replaceAll("_", " ")}
                badgeTone={plan.status === "succeeded" ? "success" : terminal ? "danger" : plan.status === "paused" ? "muted" : "accent"}
                enabled={!terminal || plan.status === "succeeded"}
                actions={
                  <>
                    {plan.status === "paused" && (
                      <ActionLink onClick={() => actions.onStartDelegation(plan)}>Start plan</ActionLink>
                    )}
                    {!terminal && <ActionLink onClick={() => actions.onCancelDelegation(plan)}>Cancel plan</ActionLink>}
                  </>
                }
              />
            );
          })}
        </div>
      </section>

      <section className="connections-section">
        <div className="panel-action-row">
          <p>Connect Telegram, Slack, GitHub, or another place.</p>
          <button type="button" className="mini-primary" onClick={actions.onNewChannel}>
            Add
          </button>
        </div>
        <div className="management-list">
          {channels.length === 0 && <EmptyState>No remote channels yet.</EmptyState>}
          {channels.map((channel) => {
            const polling = channel.kind === "telegram";
            const hookPath =
              polling ? "Laptop polls Telegram · no public URL" : `/hooks/${channel.kind}/${encodeURIComponent(channel.id)}`;
            const delivery = channel.outbound_delivery_configured ? "Replies enabled" : "Replies stored here";
            return (
              <ManagementCard
                key={channel.id}
                title={channel.name}
                meta={`${channel.kind.toUpperCase()} · ${delivery}\n${hookPath}`}
                badge={channel.enabled ? "active" : "paused"}
                enabled={channel.enabled}
                actions={
                  <>
                    {!polling && (
                      <ActionLink onClick={() => actions.onCopyWebhook(channel)}>Copy webhook URL</ActionLink>
                    )}
                    {polling && <ActionLink disabled>Polling channel</ActionLink>}
                    <ActionLink onClick={() => actions.onToggleChannel(channel)}>
                      {channel.enabled ? "Pause" : "Resume"}
                    </ActionLink>
                    <ActionLink onClick={() => actions.onDeleteChannel(channel)}>Delete</ActionLink>
                  </>
                }
              />
            );
          })}
        </div>
        <p className="section-label">Recent remote requests</p>
        <div className="management-list">
          {recentRemote.length === 0 && <EmptyState>No remote requests yet.</EmptyState>}
          {recentRemote.map((event) => (
            <ManagementCard
              key={event.id}
              title={truncate(event.text || "Remote request", 58)}
              meta={`${event.sender || "unknown"} · ${event.source || "remote"}\n${
                event.response_text ? `Reply: ${truncate(event.response_text, 90)}` : event.error || "Processing"
              }`}
              badge={event.status}
              badgeTone={
                ["failed", "cancelled"].includes(event.status)
                  ? "danger"
                  : ["responded", "stored"].includes(event.status)
                    ? "success"
                    : "accent"
              }
              enabled={!["failed", "cancelled"].includes(event.status)}
            />
          ))}
        </div>
      </section>
    </>
  );
}
