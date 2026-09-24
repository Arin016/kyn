import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../api";
import type {
  Channel,
  ChannelEvent,
  CodingExecution,
  DelegationPlan,
  Interaction,
  RunDetail,
  RunSummary,
  Task,
} from "../../types";
import { truncate } from "../../lib/format";
import "./inbox.css";

type Lane = "needs_you" | "active" | "recent";
type Filter = "all" | Lane;

interface InboxItem {
  id: string;
  lane: Lane;
  kind: string;
  title: string;
  detail: string;
  status: string;
  at: string;
  bot?: string;
  taskId?: string;
  workflowId?: string;
  runId?: string;
  channelEvent?: ChannelEvent;
  interaction?: Interaction;
}

interface Props {
  demoMode?: boolean;
  onOpenTask: (id: string) => void;
  onOpenWorkflow: (id?: string) => void;
  onOpenBot: (name: string) => void;
  onOpenChannel: (event: ChannelEvent, botName?: string) => void;
  onCreateTask: () => void;
  showToast: (message: string, isError?: boolean) => void;
}

const POLL_MS = 10_000;
const ALERTS_KEY = "ari_work_inbox_alerts";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All work" },
  { value: "needs_you", label: "Needs you" },
  { value: "active", label: "Active" },
  { value: "recent", label: "Recent" },
];

function firstLine(value: string, max = 92): string {
  return truncate(
    String(value || "Untitled work")
      .trim()
      .split("\n")[0],
    max,
  );
}

function laneForRun(status: string): Lane {
  if (status === "failed") return "needs_you";
  if (["queued", "running", "waiting_permission"].includes(status))
    return "active";
  return "recent";
}

function buildItems(data: {
  runs: RunSummary[];
  interactions: Interaction[];
  tasks: Task[];
  coding: CodingExecution[];
  workflows: DelegationPlan[];
  events: ChannelEvent[];
  channels: Channel[];
}): InboxItem[] {
  const items: InboxItem[] = [];
  const approvals = new Set(data.interactions.map((item) => item.run_id));
  const taskIds = new Set(data.tasks.map((item) => item.id));
  const channelRunIds = new Set(
    data.events.map((item) => item.run_id).filter(Boolean),
  );
  const botByChannel = new Map(
    data.channels.map((channel) => [channel.id, channel.bot_name]),
  );

  for (const interaction of data.interactions) {
    items.push({
      id: `approval:${interaction.id}`,
      lane: "needs_you",
      kind: "Approval",
      title: interaction.title || "Tool approval requested",
      detail: `${interaction.bot_name} · ${interaction.tool_name || "Tool"} · ${interaction.actor || "Ari"}`,
      status: "Waiting for you",
      at: interaction.created_at,
      bot: interaction.bot_name,
      interaction,
    });
  }

  for (const task of data.tasks) {
    const needsReview =
      task.task_status === "open" &&
      ["awaiting_handoff", "ready"].includes(task.status);
    const failed = task.task_status === "open" && task.status === "failed";
    const lane: Lane =
      needsReview || failed
        ? "needs_you"
        : task.task_status !== "open"
          ? "recent"
          : "active";
    items.push({
      id: `task:${task.id}`,
      lane,
      kind: "Coding task",
      title: firstLine(task.task || "Coding task"),
      detail: [task.builder_bot, task.branch, task.error]
        .filter(Boolean)
        .join(" · "),
      status:
        task.task_status === "merged"
          ? "Merged"
          : task.task_status === "abandoned"
            ? "Abandoned"
            : task.status.replaceAll("_", " "),
      at: task.updated_at || task.created_at || "",
      bot: task.builder_bot,
      taskId: task.id,
    });
  }

  for (const execution of data.coding) {
    if (taskIds.has(execution.id)) continue;
    const failed = execution.status === "failed";
    const review = ["awaiting_handoff", "ready"].includes(execution.status);
    const active = !["failed", "cancelled", "ready"].includes(execution.status);
    const spec = execution.spec || {};
    items.push({
      id: `coding:${execution.id}`,
      lane: failed || review ? "needs_you" : active ? "active" : "recent",
      kind: "Coding run",
      title: firstLine(spec.task || "Coding run"),
      detail: [spec.builder_bot, spec.reviewer_bot, execution.error]
        .filter(Boolean)
        .join(" · "),
      status: execution.status.replaceAll("_", " "),
      at: execution.updated_at || execution.created_at || "",
      bot: spec.builder_bot,
    });
  }

  for (const workflow of data.workflows) {
    const lane: Lane =
      workflow.status === "failed"
        ? "needs_you"
        : ["pending", "running"].includes(workflow.status)
          ? "active"
          : "recent";
    items.push({
      id: `workflow:${workflow.id}`,
      lane,
      kind: "Workflow",
      title: workflow.name || "Team workflow",
      detail: `${workflow.max_fanout || 1} parallel · depth ${workflow.max_depth || 1}`,
      status: workflow.status,
      at: workflow.updated_at || workflow.created_at || "",
      workflowId: workflow.id,
    });
  }

  for (const event of data.events) {
    const status = event.status || "received";
    const lane: Lane =
      status === "failed"
        ? "needs_you"
        : ["queued", "running"].includes(status)
          ? "active"
          : "recent";
    const bot = botByChannel.get(event.binding_id);
    items.push({
      id: `channel:${event.id}`,
      lane,
      kind: "Channel message",
      title: firstLine(
        event.text ||
          event.response_text ||
          `${event.source || "External"} message`,
      ),
      detail: [event.source, event.sender, event.error]
        .filter(Boolean)
        .join(" · "),
      status: status.replaceAll("_", " "),
      at: event.created_at || "",
      bot,
      channelEvent: event,
    });
  }

  for (const run of data.runs) {
    if (channelRunIds.has(run.id) || approvals.has(run.id)) continue;
    const lane = laneForRun(run.status);
    items.push({
      id: `run:${run.id}`,
      lane,
      kind: "Bot run",
      title: firstLine(run.message),
      detail: [run.bot_name, run.engine, run.actor, run.error]
        .filter(Boolean)
        .join(" · "),
      status: run.status.replaceAll("_", " "),
      at: run.created_at || "",
      bot: run.bot_name,
      runId: run.id,
    });
  }

  return items.sort((left, right) => {
    const laneOrder: Record<Lane, number> = {
      needs_you: 0,
      active: 1,
      recent: 2,
    };
    const attentionOrder: Record<string, number> = {
      Approval: 0,
      "Coding task": 1,
      "Coding run": 2,
      "Bot run": 3,
      Workflow: 4,
      "Channel message": 5,
    };
    const laneDifference = laneOrder[left.lane] - laneOrder[right.lane];
    if (laneDifference !== 0) return laneDifference;
    if (left.lane === "needs_you") {
      const priorityDifference =
        attentionOrder[left.kind] - attentionOrder[right.kind];
      if (priorityDifference !== 0) return priorityDifference;
    }
    const leftTime = Date.parse(left.at);
    const rightTime = Date.parse(right.at);
    if (!Number.isFinite(leftTime) || !Number.isFinite(rightTime)) return 0;
    return rightTime - leftTime;
  });
}

function relativeTime(value: string): string {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return "";
  const minutes = Math.round((Date.now() - time) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function InboxPage({
  demoMode = false,
  onOpenTask,
  onOpenWorkflow,
  onOpenBot,
  onOpenChannel,
  onCreateTask,
  showToast,
}: Props) {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [partial, setPartial] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [alertsOn, setAlertsOn] = useState(
    () => window.localStorage.getItem(ALERTS_KEY) === "on",
  );
  const [notificationPermission, setNotificationPermission] = useState<
    NotificationPermission | "unavailable"
  >(() =>
    typeof Notification === "undefined"
      ? "unavailable"
      : Notification.permission,
  );
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState("");
  const previousIds = useRef<Set<string> | null>(null);
  const runRequest = useRef(0);

  const closeRun = () => {
    runRequest.current += 1;
    setSelectedRun(null);
    setRunError("");
    setRunLoading(false);
  };

  const sendAlert = useCallback(
    async (item: InboxItem) => {
      if (
        notificationPermission !== "granted" ||
        typeof Notification === "undefined"
      )
        return;
      const options: NotificationOptions = {
        body: `${item.kind} · ${item.status}. Open Ari to review.`,
        tag: item.id,
        data: { url: `${location.pathname}#console` },
      };
      try {
        const registration =
          "serviceWorker" in navigator
            ? await navigator.serviceWorker.getRegistration()
            : undefined;
        if (registration)
          await registration.showNotification("Ari needs you", options);
        else new Notification("Ari needs you", options);
      } catch {
        // The inbox remains authoritative when browser notifications are unavailable.
      }
    },
    [notificationPermission],
  );

  const refresh = useCallback(
    async (quiet = false) => {
      if (demoMode) {
        setItems([]);
        setLoading(false);
        return;
      }
      if (quiet) setRefreshing(true);
      else setLoading(true);
      const results = await Promise.allSettled([
        api.runs(),
        api.interactions(undefined, "pending"),
        api.tasks(),
        api.codingExecutions(),
        api.delegations(),
        api.channelEvents(),
        api.channels(),
      ]);
      const values = results.map((result) =>
        result.status === "fulfilled" ? result.value : [],
      );
      const nextItems = buildItems({
        runs: values[0] as RunSummary[],
        interactions: values[1] as Interaction[],
        tasks: values[2] as Task[],
        coding: values[3] as CodingExecution[],
        workflows: values[4] as DelegationPlan[],
        events: values[5] as ChannelEvent[],
        channels: values[6] as Channel[],
      });
      const oldIds = previousIds.current;
      if (oldIds && alertsOn && document.hidden) {
        for (const item of nextItems) {
          if (item.lane === "needs_you" && !oldIds.has(item.id))
            void sendAlert(item);
        }
      }
      previousIds.current = new Set(nextItems.map((item) => item.id));
      setItems(nextItems);
      setPartial(results.some((result) => result.status === "rejected"));
      setLoading(false);
      setRefreshing(false);
    },
    [alertsOn, demoMode, sendAlert],
  );

  useEffect(() => {
    void refresh();
    if (demoMode) return;
    const timer = window.setInterval(() => void refresh(true), POLL_MS);
    return () => window.clearInterval(timer);
  }, [demoMode, refresh]);

  const counts = useMemo(
    () => ({
      needs_you: items.filter((item) => item.lane === "needs_you").length,
      active: items.filter((item) => item.lane === "active").length,
      recent: items.filter((item) => item.lane === "recent").length,
    }),
    [items],
  );

  const visible = items.filter((item) => {
    const matchesLane = filter === "all" || item.lane === filter;
    const needle = query.trim().toLocaleLowerCase();
    const matchesQuery =
      !needle ||
      `${item.kind} ${item.title} ${item.detail} ${item.status}`
        .toLocaleLowerCase()
        .includes(needle);
    return matchesLane && matchesQuery;
  });
  const runEvents = (selectedRun?.events || [])
    .filter((event) =>
      [
        "tool_call",
        "tool_call_update",
        "interaction_required",
        "permission",
        "complete",
        "error",
      ].includes(event.kind || ""),
    )
    .slice(-100);

  const decide = async (item: InboxItem, decision: "once" | "reject") => {
    if (!item.interaction) return;
    setBusy(item.id);
    try {
      await api.decideInteraction(item.interaction.id, decision);
      showToast(
        decision === "once" ? "Approved this action once." : "Action denied.",
      );
      await refresh(true);
    } catch (error) {
      showToast(
        (error as Error).message || "Could not save that decision.",
        true,
      );
    } finally {
      setBusy(null);
    }
  };

  const toggleAlerts = async () => {
    if (alertsOn) {
      window.localStorage.setItem(ALERTS_KEY, "off");
      setAlertsOn(false);
      return;
    }
    if (typeof Notification === "undefined") {
      showToast("This browser does not support desktop notifications.", true);
      return;
    }
    let permission = Notification.permission;
    if (permission === "default")
      permission = await Notification.requestPermission();
    setNotificationPermission(permission);
    if (permission !== "granted") {
      showToast(
        permission === "denied"
          ? "Allow notifications for Ari in your browser settings."
          : "Notifications were not enabled.",
        true,
      );
      return;
    }
    window.localStorage.setItem(ALERTS_KEY, "on");
    setAlertsOn(true);
    showToast("Work inbox alerts enabled.");
  };

  const openItem = (item: InboxItem) => {
    if (item.taskId) return onOpenTask(item.taskId);
    if (item.workflowId) return onOpenWorkflow(item.workflowId);
    if (item.runId) {
      const requestId = ++runRequest.current;
      setSelectedRun(null);
      setRunError("");
      setRunLoading(true);
      void api
        .run(item.runId)
        .then((run) => {
          if (runRequest.current === requestId) setSelectedRun(run);
        })
        .catch((error) => {
          if (runRequest.current === requestId)
            setRunError((error as Error).message || "Could not load this run.");
        })
        .finally(() => {
          if (runRequest.current === requestId) setRunLoading(false);
        });
      return;
    }
    if (item.channelEvent) return onOpenChannel(item.channelEvent, item.bot);
    if (item.bot) return onOpenBot(item.bot);
    if (item.kind === "Workflow") return onOpenWorkflow();
  };

  useEffect(() => {
    if (!selectedRun && !runLoading && !runError) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeRun();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedRun, runLoading, runError]);

  const sections: { key: Lane; title: string; description: string }[] = [
    {
      key: "needs_you",
      title: "Needs you",
      description: "Approvals, reviews, and failures that need a decision.",
    },
    {
      key: "active",
      title: "In progress",
      description: "Work Ari is currently running or has queued.",
    },
    {
      key: "recent",
      title: "Recent",
      description: "Finished work and recent channel activity.",
    },
  ];

  return (
    <section className="inbox-page" aria-label="Work inbox">
      <header className="inbox-header">
        <div>
          <p className="eyebrow">Control room</p>
          <h1>Work inbox</h1>
          <p className="inbox-lead">
            Decisions, active work, and finished runs — together.
          </p>
        </div>
        <div className="inbox-header-actions">
          {notificationPermission !== "unavailable" && (
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => void toggleAlerts()}
              disabled={notificationPermission === "denied" && !alertsOn}
              title={
                notificationPermission === "denied"
                  ? "Allow notifications for Ari in your browser settings."
                  : undefined
              }
            >
              {alertsOn
                ? "Pause alerts"
                : notificationPermission === "denied"
                  ? "Alerts blocked"
                  : "Enable alerts"}
            </button>
          )}
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={() => void refresh(true)}
            disabled={refreshing}
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="inbox-summary" aria-label="Work summary">
        {(
          [
            ["needs_you", "Needs your attention", "Decisions and reviews"],
            ["active", "In progress", "Work running now"],
            ["recent", "Recently finished", "Completed and closed"],
          ] as const
        ).map(([key, label, hint]) => (
          <button
            key={key}
            type="button"
            aria-pressed={filter === key}
            onClick={() => setFilter(filter === key ? "all" : key)}
          >
            <strong>{counts[key]}</strong>
            <span>{label}</span>
            <small>{hint}</small>
          </button>
        ))}
      </div>

      <div className="inbox-toolbar">
        <label className="inbox-search">
          <span aria-hidden>⌕</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find a task, bot, or run"
            aria-label="Search work"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </label>
        <nav className="inbox-filters" aria-label="Filter work">
          {FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={filter === option.value}
              onClick={() => setFilter(option.value)}
            >
              {option.label}
              {option.value !== "all" && <span>{counts[option.value]}</span>}
            </button>
          ))}
        </nav>
      </div>

      {demoMode && (
        <p className="inbox-note">
          Connect a local Ari daemon to see live runs and decisions.
        </p>
      )}
      {partial && (
        <p className="inbox-note" role="status">
          Some work sources could not be refreshed. Showing the sources that
          responded.
        </p>
      )}

      {loading ? (
        <p className="inbox-empty">Loading work…</p>
      ) : visible.length === 0 ? (
        <div className="inbox-empty-state">
          <span className="inbox-empty-mark" aria-hidden>
            {query ? "⌕" : filter === "needs_you" ? "✓" : "↗"}
          </span>
          <p className="eyebrow">
            {query
              ? "Search"
              : filter === "needs_you"
                ? "Clear runway"
                : "Your workspace"}
          </p>
          <h2>
            {query
              ? "No work matches that search"
              : filter === "needs_you"
                ? "You’re all caught up"
                : "Give your agents something to do"}
          </h2>
          <p>
            {query
              ? "Try another task name, bot, or status."
              : filter === "needs_you"
                ? "Approvals and reviews will appear here when a decision is needed."
                : "Start a task or workflow. Ari will bring the important decisions back here."}
          </p>
          {query ? (
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => setQuery("")}
            >
              Clear search
            </button>
          ) : (
            <div className="inbox-empty-actions">
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={onCreateTask}
              >
                ＋ Start a task
              </button>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => onOpenWorkflow()}
              >
                Create a workflow
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="inbox-sections">
          {sections
            .filter((section) => filter === "all" || section.key === filter)
            .map((section) => {
              const rows = visible
                .filter((item) => item.lane === section.key)
                .slice(0, section.key === "recent" ? 30 : 100);
              if (rows.length === 0) return null;
              return (
                <section
                  className="inbox-section"
                  key={section.key}
                  aria-label={section.title}
                >
                  <header>
                    <div>
                      <h2>{section.title}</h2>
                      <p>{section.description}</p>
                    </div>
                    <span>{rows.length}</span>
                  </header>
                  <ul>
                    {rows.map((item) => (
                      <li
                        className="inbox-item"
                        key={item.id}
                        data-lane={item.lane}
                      >
                        <span className="inbox-item-mark" aria-hidden />
                        <div className="inbox-item-main">
                          <div className="inbox-item-titleline">
                            <span className="inbox-kind">{item.kind}</span>
                            <time>{relativeTime(item.at)}</time>
                          </div>
                          <h3>{item.title}</h3>
                          <p>{item.detail || item.status}</p>
                        </div>
                        <span className="inbox-status">{item.status}</span>
                        <div className="inbox-item-actions">
                          {item.interaction ? (
                            <>
                              <button
                                type="button"
                                className="btn btn-sm btn-primary"
                                disabled={busy === item.id}
                                onClick={() => void decide(item, "once")}
                              >
                                Allow once
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm btn-secondary"
                                disabled={busy === item.id}
                                onClick={() => void decide(item, "reject")}
                              >
                                Deny
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              className="btn btn-sm btn-secondary"
                              onClick={() => openItem(item)}
                            >
                              {item.taskId
                                ? "Review task"
                                : item.workflowId
                                  ? "Open workflow"
                                  : item.runId
                                    ? "Inspect run"
                                    : item.channelEvent
                                      ? "Open message"
                                      : item.bot
                                        ? "Open bot"
                                        : "Open"}
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
        </div>
      )}
      {(selectedRun || runLoading || runError) && (
        <div
          className="modal-root inbox-run-overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeRun();
          }}
        >
          <section
            className="modal-dialog modal-dialog-wide inbox-run-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="inbox-run-title"
          >
            <header className="inbox-run-header">
              <div>
                <p className="eyebrow">Run diagnostics</p>
                <h2 id="inbox-run-title">
                  {selectedRun?.bot_name || "Run details"}
                </h2>
              </div>
              <button
                type="button"
                className="modal-close"
                aria-label="Close run details"
                onClick={closeRun}
              >
                ×
              </button>
            </header>
            {runLoading ? (
              <p className="inbox-run-note">Loading run history…</p>
            ) : runError ? (
              <p className="inbox-run-error" role="alert">
                {runError}
              </p>
            ) : (
              selectedRun && (
                <div className="inbox-run-content">
                  <div className="inbox-run-facts">
                    <span>
                      <small>Status</small>
                      {selectedRun.status.replaceAll("_", " ")}
                    </span>
                    {selectedRun.engine && (
                      <span>
                        <small>Engine</small>
                        {selectedRun.engine}
                      </span>
                    )}
                    {selectedRun.started_at && (
                      <span>
                        <small>Started</small>
                        {relativeTime(selectedRun.started_at)}
                      </span>
                    )}
                    {selectedRun.finished_at && (
                      <span>
                        <small>Finished</small>
                        {relativeTime(selectedRun.finished_at)}
                      </span>
                    )}
                    {selectedRun.stop_reason && (
                      <span>
                        <small>Stop reason</small>
                        {selectedRun.stop_reason.replaceAll("_", " ")}
                      </span>
                    )}
                  </div>
                  {selectedRun.error && (
                    <div className="inbox-run-error" role="status">
                      <strong>Failure detail</strong>
                      <p>{selectedRun.error}</p>
                    </div>
                  )}
                  <p className="inbox-run-prompt">{selectedRun.message}</p>
                  <h3>Execution trail</h3>
                  {runEvents.length ? (
                    <ol className="inbox-run-events">
                      {runEvents.map((event, index) => (
                        <li
                          key={`${event.sequence ?? index}-${event.kind}`}
                          data-kind={event.kind}
                        >
                          <span>
                            {(event.kind || "event").replaceAll("_", " ")}
                          </span>
                          <p>
                            {event.title ||
                              event.tool_name ||
                              event.stop_reason ||
                              (event.kind === "error" ? event.text : "") ||
                              "Step recorded"}
                          </p>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="inbox-run-note">
                      Detailed steps are available only while this process still
                      has the run in memory. The run status and failure summary
                      above remain available after restart.
                    </p>
                  )}
                </div>
              )
            )}
          </section>
        </div>
      )}
    </section>
  );
}
