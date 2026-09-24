import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "./api";
import { wsUrl, useWebSocket } from "./hooks/useWebSocket";
import { ToastProvider, useToast } from "./hooks/useToast";
import { useStickToBottom } from "./lib/useStickToBottom";
import { isDemoParam, isMarketingDeploy } from "./lib/deploy";
import {
  DEMO_BOTS,
  DEMO_CHANNEL,
  DEMO_CHANNEL_EVENTS,
  DEMO_GROUP_DETAIL,
  DEMO_THREADS,
  demoManagementData,
  demoResponseFor,
} from "./lib/demoConsole";
import EngineeringPage from "./pages/EngineeringPage";
import LandingPage from "./pages/LandingPage";
import { BotAvatar } from "./components/BotAvatar";
import { AriGlyph } from "./components/AriGlyph";
import { ModelSwitcher } from "./components/ModelSwitcher";
import { buildBotCommands } from "./lib/slash";
import { applyTheme } from "./lib/theme";
import { KIRO_MODELS } from "./components/dialogs/Dialogs";
import { Thread } from "./components/chat/Thread";
import type { Part } from "./components/chat/Message";
import { Composer } from "./components/chat/Composer";
import { ThinkingGhost } from "./components/chat/ThinkingGhost";
import { Sidebar } from "./components/Sidebar";
import { GroupChat } from "./components/group/GroupChat";
import { PluginPlaceBoard } from "./components/plugins/PluginPlaceBoard";
import { TaskBoard } from "./components/tasks/TaskBoard";
import { InboxPage } from "./components/inbox/InboxPage";
import { SetupWizard } from "./components/setup/SetupWizard";
import { WorkflowPlayground } from "./components/workflows/WorkflowPlayground";
import {
  InspectPanel,
  type InspectTab,
  type ManagementData,
} from "./components/inspect/InspectPanel";
import type { WorkActions } from "./components/inspect/WorkTab";
import type { SafetyActions } from "./components/inspect/SafetyTab";
import {
  ChannelDialog,
  CodingDialog,
  CreateBotDialog,
  CreateGroupDialog,
  HandoffDialog,
  PluginDialog,
  RoutineDialog,
  TaskDialog,
} from "./components/dialogs/Dialogs";
import type {
  AuditItem,
  Bot,
  Channel,
  ChannelEvent,
  CodingExecution,
  DelegationPlan,
  Group as GroupChatRecord,
  HistoryTurn,
  Interaction,
  LiveMessage,
  PermissionRequest,
  Plugin,
  Policy,
  Routine,
  RunPhase,
  StreamEnvelope,
  Surface,
  TimelineEntry,
} from "./types";

type DialogName =
  | "bot"
  | "group"
  | "routine"
  | "plugin"
  | "channel"
  | "coding"
  | "task"
  | "handoff"
  | null;

interface ActiveRun {
  id: string;
}

const PHASE_TITLE: Record<RunPhase, string> = {
  idle: "Idle",
  starting: "Starting",
  running: "Working",
  waiting: "Approval needed",
  stopping: "Stopping",
  error: "Error",
};

const SUGGESTIONS = [
  {
    title: "Understand this project",
    detail: "Get a quick map of what it does",
    prompt: "Summarize what this repo does",
  },
  {
    title: "Review recent changes",
    detail: "Spot risk in the latest work",
    prompt: "What changed here recently?",
  },
  {
    title: "Rank open TODOs",
    detail: "Find the most urgent unfinished work",
    prompt: "Find TODOs and rank them by urgency",
  },
  {
    title: "Add a safety net",
    detail: "Test the riskiest paths",
    prompt: "Write tests for the riskiest module",
  },
];

const CHIEF_SUGGESTIONS = [
  {
    title: "Review the fleet",
    detail: "See what's running, waiting, and blocked",
    prompt: "Show me the fleet status",
  },
  {
    title: "Create a reviewer",
    detail: "Build a specialist for this repo",
    prompt: "Create a reviewer bot for this repo",
  },
  {
    title: "Change a model",
    detail: "Switch builder to Claude Sonnet 4.5",
    prompt: "Switch builder to Claude Sonnet 4.5",
  },
  {
    title: "Automate a check",
    detail: "Schedule a nightly repository check",
    prompt: "Schedule a nightly repo check for builder",
  },
];

function eventId(payload: unknown): number {
  const record = payload as Record<string, unknown>;
  return Number(record?.id || record?.sequence || record?.offset || 0);
}

function parseEvent(payload: unknown): Record<string, unknown> {
  if (typeof payload === "string") {
    try {
      return JSON.parse(payload) as Record<string, unknown>;
    } catch {
      return { kind: "text", text: payload };
    }
  }
  return (payload as Record<string, unknown>) || {};
}

function eventText(event: Record<string, unknown>): string {
  return String(
    event.text || event.content || event.message || event.title || "",
  );
}

function normalizeBots(data: unknown): Bot[] {
  const list = Array.isArray(data)
    ? data
    : ((data as Record<string, unknown>)?.bots as unknown[]) ||
      ((data as Record<string, unknown>)?.items as unknown[]) ||
      [];
  return list
    .filter(Boolean)
    .map((bot) => (typeof bot === "string" ? { name: bot } : (bot as Bot)));
}

function normalizeHistory(data: unknown): HistoryTurn[] {
  if (Array.isArray(data)) return data as HistoryTurn[];
  const record = data as Record<string, unknown>;
  return (
    ((record?.turns ||
      record?.history ||
      record?.items ||
      []) as HistoryTurn[]) || []
  );
}

function turnPrompt(turn: HistoryTurn): string {
  return String(turn.prompt || turn.message || turn.input || "");
}

interface TurnSection {
  id: string;
  turnId?: number;
  prompt: string;
  parts: Part[];
}

function mapTurnParts(turn: HistoryTurn, turnIndex: number): Part[] {
  const parts: Part[] = [];
  const prompt = turn.prompt || turn.message || turn.input || "";
  if (prompt) parts.push({ type: "user", text: String(prompt) });
  const storedEvents = turn.events || turn.activity || [];
  let buffer = "";
  let sawText = false;
  storedEvents.forEach((storedEvent, eventIndex) => {
    const event =
      storedEvent?.payload && typeof storedEvent.payload === "object"
        ? (storedEvent.payload as Record<string, unknown>)
        : (storedEvent as unknown as Record<string, unknown>);
    const kind = String(
      event.kind || storedEvent.kind || event.type || "event",
    );
    const text = eventText(event);
    const key = `h-${turnIndex}-${eventIndex}`;
    if (
      kind === "text" ||
      kind === "agent_message_chunk" ||
      kind === "assistant"
    ) {
      buffer += text;
      sawText = true;
    } else if (kind === "thinking" || kind === "agent_thought_chunk") {
      if (text.trim())
        parts.push({ type: "reasoning", id: key, text, running: false });
    } else if (kind === "failover") {
      const note = text || "Engine failover";
      if (note) parts.push({ type: "note", text: note });
    } else if (kind.includes("tool")) {
      const title = String(event.title || text || "Tool activity");
      const previous = parts[parts.length - 1];
      if (previous && previous.type === "tool" && previous.title === title) {
        previous.title = `${title} ×${(previous.repeat || 1) + 1}`;
        previous.repeat = (previous.repeat || 1) + 1;
      } else {
        parts.push({
          type: "tool",
          id: key,
          title,
          status: "done",
        });
      }
    }
  });
  if (sawText) parts.push({ type: "assistant-text", text: buffer });
  // Persist the last usage snapshot of the turn as the thread's usage state.
  const usageSnapshots = storedEvents.filter((storedEvent) => {
    const evt = (storedEvent?.payload ?? storedEvent) as Record<
      string,
      unknown
    >;
    const k = String(evt.kind || storedEvent.kind || evt.type || "");
    return k === "usage" || k === "usage_update";
  });
  if (usageSnapshots.length > 0) {
    const last = (usageSnapshots[usageSnapshots.length - 1]?.payload ??
      usageSnapshots[usageSnapshots.length - 1]) as Record<string, unknown>;
    const tokens = Number(last.used ?? last.current_token_use ?? 0);
    const cost = Number(last.cost ?? last.current_cost_usd ?? 0);
    // A zero/zero snapshot carries no information — never render a pill for it.
    if (
      Number.isFinite(tokens) &&
      Number.isFinite(cost) &&
      (tokens !== 0 || cost !== 0)
    ) {
      parts.push({ type: "usage", id: `h-${turnIndex}-usage`, tokens, cost });
    }
  }
  return parts;
}

/** Freeze transient flags once a run ends. */
function finalizeParts(parts: Part[]): Part[] {
  let changed = false;
  const next = parts.map((part) => {
    if (part.type === "assistant-text" && part.streaming) {
      changed = true;
      return { ...part, streaming: false };
    }
    if (part.type === "reasoning" && part.running) {
      changed = true;
      return { ...part, running: false };
    }
    if (part.type === "tool" && part.status === "running") {
      changed = true;
      return { ...part, status: "done" as const };
    }
    return part;
  });
  return changed ? next : parts;
}

function channelToParts(
  surface: Surface,
  channelEvents: ChannelEvent[],
  channelLabel: string,
): Part[] {
  if (surface.kind !== "channel") return [];
  const events = channelEvents
    .filter(
      (event) =>
        event.binding_id === surface.id &&
        (!surface.threadKey || event.thread_key === surface.threadKey),
    )
    .sort((a, b) =>
      String(a.created_at ?? "").localeCompare(String(b.created_at ?? "")),
    );
  const parts: Part[] = [];
  events.forEach((event, index) => {
    parts.push({
      type: "channel",
      text: String(event.text || ""),
      label: channelLabel,
    });
    if (event.response_text) {
      parts.push({ type: "assistant-text", text: String(event.response_text) });
    } else if (["queued", "running"].includes(event.status)) {
      parts.push({ type: "assistant-text", text: "", streaming: true });
    } else if (event.error) {
      parts.push({ type: "error", text: String(event.error) });
    }
    void index;
  });
  return parts;
}

function RunStream({
  run,
  onEvent,
}: {
  run: ActiveRun;
  onEvent: (envelope: StreamEnvelope) => void;
}) {
  const afterRef = useRef(0);
  // WS and the 1.8s poll overlap: both can deliver the same sequence twice.
  // Track delivered sequence IDs so a replay never double-appends text.
  const deliveredRef = useRef<Set<number>>(new Set());

  const handleMessage = useCallback(
    (payload: unknown) => {
      const envelope = payload as StreamEnvelope;
      const id = eventId(envelope) || eventId(envelope.event);
      if (id > afterRef.current) afterRef.current = id;
      if (Number.isFinite(id) && id > 0) {
        if (deliveredRef.current.has(id)) return;
        deliveredRef.current.add(id);
        // Bounded: runs cap event retention, so cap the set too.
        if (deliveredRef.current.size > 6000) deliveredRef.current.clear();
      }
      onEvent(envelope);
    },
    [onEvent],
  );

  useWebSocket(
    useCallback(
      () =>
        wsUrl(
          `/ws/runs/${encodeURIComponent(run.id)}?after=${afterRef.current}`,
        ),
      [run.id],
    ),
    handleMessage,
  );

  useEffect(() => {
    // Poll fallback keeps the thread moving even if WS upgrades are blocked.
    let cancelled = false;
    let timer = 0;
    const poll = async () => {
      try {
        const data = await api.pollRun(run.id, afterRef.current);
        const record = (data ?? {}) as Record<string, unknown>;
        const events = Array.isArray(data)
          ? (data as unknown[])
          : ((record.events || record.items || []) as unknown[]);
        for (const item of events) handleMessage(item as StreamEnvelope);
        const status = String(record.status || record.state || "");
        if (
          status &&
          ["complete", "completed", "cancelled", "failed", "error"].includes(
            status.toLowerCase(),
          )
        ) {
          if (!cancelled) {
            onEvent({
              type: "terminal",
              run: {
                status:
                  status === "failed" || status === "error" ? "failed" : status,
                error:
                  typeof record.detail === "string" ? record.detail : undefined,
              },
            });
          }
          return;
        }
      } catch {
        /* transient */
      }
      if (!cancelled) timer = window.setTimeout(poll, 1800);
    };
    timer = window.setTimeout(poll, 1800);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [run.id, handleMessage, onEvent]);

  return null;
}

function ControlRoom({ onExit }: { onExit: () => void }) {
  const { showToast } = useToast();
  const marketing = isMarketingDeploy || isDemoParam;
  const demoStreamRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (demoStreamRef.current) window.clearInterval(demoStreamRef.current);
    };
  }, []);

  const [bots, setBots] = useState<Bot[]>([]);
  const [selectedBot, setSelectedBot] = useState<Bot | null>(null);
  const [groups, setGroups] = useState<GroupChatRecord[]>([]);
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [surface, setSurface] = useState<Surface>({ kind: "local" });
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [runDetail, setRunDetail] = useState("");
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const [queuedRuns, setQueuedRuns] = useState<string[]>([]);
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const queuedRef = useRef<string[]>([]);
  queuedRef.current = queuedRuns;
  const [parts, setParts] = useState<Part[]>([]);
  // Durable turns behind the live buffer. `parts` is append-only live state
  // (optimistic echoes + streamed events); history sections render beneath.
  const [historyTurns, setHistoryTurns] = useState<HistoryTurn[]>([]);
  // Draft pushed into the composer by turn actions (Edit & rerun).
  const [composerDraft, setComposerDraft] = useState<{
    text: string;
    nonce: number;
  } | null>(null);
  const [permissions, setPermissions] = useState<PermissionRequest[]>([]);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelEvents, setChannelEvents] = useState<ChannelEvent[]>([]);
  const [unread, setUnread] = useState<Record<string, number>>({});
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [connected, setConnected] = useState(false);
  const [inspectPinned, setInspectPinned] = useState(false);
  const [inspectTab, setInspectTab] = useState<InspectTab>("run");
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900);
  const [headerMoreOpen, setHeaderMoreOpen] = useState(false);
  const headerMoreRef = useRef<HTMLDivElement>(null);
  const [dialog, setDialog] = useState<DialogName>(null);
  const [workspace, setWorkspace] = useState<
    "conversation" | "inbox" | "workflows" | "tasks" | "plugins"
  >("conversation");
  const [inboxTaskId, setInboxTaskId] = useState<string | null>(null);
  const [inboxWorkflowId, setInboxWorkflowId] = useState<string | null>(null);

  useEffect(() => {
    if (!headerMoreOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !headerMoreRef.current?.contains(event.target)
      ) {
        setHeaderMoreOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setHeaderMoreOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [headerMoreOpen]);

  const [usageRefreshKey, setUsageRefreshKey] = useState(0);
  const [management, setManagement] = useState<ManagementData>({
    policy: null,
    routines: [],
    plugins: [],
    bindings: [],
    audit: [],
    delegations: [],
    codingExecutions: [],
    channels: [],
    channelEvents: [],
    memoryRecords: [],
    memoryFacts: [],
  });

  const timelineIdRef = useRef(0);
  const activeRunRef = useRef<ActiveRun | null>(null);
  activeRunRef.current = activeRun;
  // Synchronous identity for async guards (selectedBot state lags awaits).
  const selectedBotRef = useRef<Bot | null>(null);
  selectedBotRef.current = selectedBot;

  const { containerRef, stuck, onScroll, bump, scrollToLatest } =
    useStickToBottom();

  useEffect(() => {
    bump();
  }, [parts, bump]);

  const addTimeline = useCallback(
    (kind: TimelineEntry["kind"], detail: string) => {
      timelineIdRef.current += 1;
      const entry: TimelineEntry = {
        id: Date.now() * 1000 + timelineIdRef.current,
        kind,
        detail: detail || kind.replaceAll("_", " "),
        at: new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      };
      setTimeline((current) => {
        const latest = current[0];
        if (latest && latest.kind === kind && latest.detail === entry.detail)
          return current;
        return [entry, ...current];
      });
    },
    [],
  );

  const finishRun = useCallback((nextPhase: RunPhase, detail: string) => {
    setPhase(nextPhase);
    setRunDetail(detail);
    setUsageRefreshKey((value) => value + 1);
    setPermissions([]);
    setParts((current) => finalizeParts(current));
    setActiveRun(null);
    setRunStartedAt(null);
  }, []);

  const attachNextQueued = useCallback(() => {
    const next = queuedRef.current[0];
    if (!next) return;
    setQueuedRuns((current) => current.slice(1));
    setActiveRun({ id: next });
    setPhase("running");
    setRunDetail("Running queued message…");
    setRunStartedAt(Date.now());
    addTimeline("info", "Starting queued message");
  }, []);

  const knownBotsRef = useRef<Set<string> | null>(null);

  const loadBots = useCallback(
    async (options?: { announce?: boolean; quiet?: boolean }) => {
      if (marketing) {
        setBots(DEMO_BOTS);
        setSelectedBot(DEMO_BOTS[0]);
        setChannels([DEMO_CHANNEL]);
        setChannelEvents(DEMO_CHANNEL_EVENTS);
        setManagement(demoManagementData());
        setParts(DEMO_THREADS[DEMO_BOTS[0].name] ?? []);
        setConnected(true);
        return;
      }
      try {
        const data = await api.listBots();
        const list = normalizeBots(data);
        setBots(list);
        setConnected(true);
        // Keep the selected bot's record fresh (model/engine edits land here).
        setSelectedBot((current) =>
          current
            ? list.find((bot) => bot.name === current.name) || current
            : current,
        );
        // Bots can be born outside this window — chief's fleet tools, the CLI,
        // another surface. Announce newcomers instead of making the user reload.
        const known = knownBotsRef.current;
        if (known === null) {
          knownBotsRef.current = new Set(list.map((bot) => bot.name));
        } else if (options?.announce !== false) {
          for (const bot of list) {
            if (!known.has(bot.name)) {
              known.add(bot.name);
              showToast(`New bot '${bot.name}' joined the fleet`, false);
            }
          }
          for (const name of [...known]) {
            if (!list.some((bot) => bot.name === name)) known.delete(name);
          }
        }
        const requested = new URLSearchParams(location.search).get("bot");
        const preferred = list.find((bot) => bot.name === requested);
        if (preferred) setSelectedBot(preferred);
      } catch (error) {
        setConnected(false);
        if (!options?.quiet)
          showToast((error as Error).message || "Could not load bots", true);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [marketing],
  );

  const loadGroups = useCallback(async () => {
    if (marketing) {
      setGroups([DEMO_GROUP_DETAIL.group]);
      return;
    }
    try {
      setGroups(await api.groups());
    } catch {
      setGroups([]);
    }
  }, [marketing]);

  const receiveEvent = useCallback(
    (envelope: StreamEnvelope) => {
      if (envelope.type === "terminal") {
        const status = envelope.run?.status || "complete";
        if (status === "failed") {
          const message = envelope.run?.error || "Run failed";
          setParts((current) => [
            ...finalizeParts(current),
            { type: "error", text: message },
          ]);
          finishRun("error", message);
          addTimeline("error", message);
        } else {
          finishRun(
            "idle",
            envelope.run?.stop_reason ||
              (status === "cancelled" ? "Run cancelled" : "Run complete"),
          );
          addTimeline("complete", "Run completed");
        }
        // A finished run may have created bots, groups, or routines behind
        // our back — re-read the roster immediately, not on the next poll.
        void loadBots({ quiet: true });
        void loadGroups();
        attachNextQueued();
        return;
      }
      if (envelope.type === "error" && !envelope.kind) {
        // A stream-level error is not a run verdict: the run may still be
        // executing and the socket reconnects on its own (the poll fallback
        // also replays terminal state). Keep the run mounted; only terminal
        // envelopes may clear it — otherwise queued runs would be orphaned.
        const detail = envelope.detail || "Live stream failed";
        setParts((current) => [
          ...finalizeParts(current),
          { type: "error", text: detail },
        ]);
        showToast(detail, true);
        addTimeline("error", detail);
        return;
      }

      const raw = envelope.event || envelope.data || (envelope as unknown);
      const event = parseEvent(raw);
      const kind = String(event.kind || event.type || "event");
      const text = eventText(event);

      if (
        kind === "text" ||
        kind === "agent_message_chunk" ||
        kind === "assistant"
      ) {
        setParts((current) => {
          const last = current[current.length - 1];
          if (last?.type === "assistant-text") {
            const next = [...current];
            next[next.length - 1] = {
              ...last,
              text: last.text + text,
              streaming: true,
            };
            return next;
          }
          return [
            ...current,
            { type: "assistant-text", text, streaming: true },
          ];
        });
      } else if (kind === "thinking" || kind === "agent_thought_chunk") {
        if (!text) return;
        setParts((current) => {
          const last = current[current.length - 1];
          if (last?.type === "reasoning" && last.running) {
            const next = [...current];
            next[next.length - 1] = { ...last, text: `${last.text}${text}` };
            return next;
          }
          return [
            ...current,
            { type: "reasoning", id: crypto.randomUUID(), text, running: true },
          ];
        });
      } else if (kind === "permission" || kind === "interaction_required") {
        const id = String(
          event.interaction_id ||
            event.request_id ||
            event.requestId ||
            event.id ||
            crypto.randomUUID(),
        );
        const requestId = String(event.request_id || event.requestId || "");
        setPhase("waiting");
        setRunDetail(
          String(event.title || "Kiro needs permission to continue."),
        );
        setPermissions((current) =>
          current.some((item) => item.id === id)
            ? current
            : [
                ...current,
                {
                  id,
                  title: String(event.title || ""),
                  runId: activeRunRef.current?.id,
                  requestId,
                  toolName: String(event.tool_name || ""),
                },
              ],
        );
        setParts((current) =>
          current.some((part) => part.type === "approval" && part.id === id)
            ? current
            : [
                ...current,
                { type: "approval", id, title: String(event.title || "") },
              ],
        );
        addTimeline(
          "permission",
          String(event.title || "Permission requested"),
        );
      } else if (kind.includes("tool")) {
        const title = String(event.title || text || "Tool activity");
        setParts((current) => {
          const last = current[current.length - 1];
          // Collapse consecutive repeats like the history path does (×N).
          // Thread.groupParts batches consecutive tool parts into one row, so
          // appending is always safe — replayed envelopes are already deduped
          // by sequence upstream.
          if (
            last?.type === "tool" &&
            last.title.replace(/ ×\d+$/, "") === title
          ) {
            const repeat = (last.repeat || 1) + 1;
            const next = [...current];
            next[next.length - 1] = {
              ...last,
              title: `${title} ×${repeat}`,
              repeat,
            };
            return next;
          }
          return [
            ...current,
            {
              type: "tool",
              id: crypto.randomUUID(),
              title,
              status: "done" as const,
            },
          ];
        });
        addTimeline("tool", title);
        if (activeRunRef.current) {
          setPhase((currentPhase) =>
            currentPhase === "waiting" ? currentPhase : "running",
          );
          setRunDetail(title);
        }
      } else if (kind === "failover") {
        const note = text || "Engine failover";
        setParts((current) => [...current, { type: "note", text: note }]);
        addTimeline("error", note);
      } else if (kind === "usage" || kind === "usage_update") {
        // ACP semantics: `used` is the context-window snapshot, `cost` is the
        // cumulative session cost. Show the LATEST snapshot only — never sum them.
        // A zero/zero snapshot carries no information — never render a pill for it.
        const tokens = Number(event.used ?? event.current_token_use ?? 0);
        const cost = Number(event.cost ?? event.current_cost_usd ?? 0);
        if (!Number.isFinite(tokens) || !Number.isFinite(cost)) return;
        if (tokens === 0 && cost === 0) {
          setParts((current) =>
            current.some((part) => part.type === "usage")
              ? current.filter((part) => part.type !== "usage")
              : current,
          );
          return;
        }
        const usage = {
          type: "usage",
          id: `usage-${Date.now()}`,
          tokens,
          cost,
        } as Part;
        setParts((current) => {
          // Replace in place: filter+append would shift every follower's
          // index key and remount them (index keys are stable only because
          // this thread is append-only — keep it that way).
          const at = current.findIndex((part) => part.type === "usage");
          if (at === -1) return [...current, usage];
          const next = [...current];
          next[at] = usage;
          return next;
        });
      } else if (kind === "complete" || kind === "done") {
        finishRun("idle", String(event.stop_reason || "Run complete"));
        addTimeline("complete", "Run completed");
      } else if (kind === "error" || kind === "failed") {
        const message = text || "The run failed";
        setParts((current) => [
          ...finalizeParts(current),
          { type: "error", text: message },
        ]);
        finishRun("error", message);
        addTimeline("error", message);
        showToast(message, true);
      }
    },
    [addTimeline, attachNextQueued, finishRun, showToast, loadBots, loadGroups],
  );

  const handleStreamEvent = useCallback(
    (envelope: StreamEnvelope) => receiveEvent(envelope),
    [receiveEvent],
  );

  // ---- Live room -------------------------------------------------------

  const upsertChannelEvent = useCallback((event: ChannelEvent) => {
    setChannelEvents((current) => {
      const index = current.findIndex((item) => item.id === event.id);
      if (index >= 0) {
        const next = [...current];
        next[index] = event;
        return next;
      }
      return [event, ...current];
    });
  }, []);

  const onLiveMessage = useCallback(
    (payload: unknown) => {
      const message = payload as LiveMessage;
      if (!message || typeof message !== "object") return;
      // Roster push from the daemon: a bot or group changed somewhere (chief's
      // fleet tools, another tab, the CLI relay). Re-read that scope now —
      // this is what makes creation feel instant instead of poll-lagged.
      if (message.type === "roster") {
        if (message.scope === "bots") void loadBots({ quiet: true });
        else if (message.scope === "groups") void loadGroups();
        return;
      }
      if (message.type !== "channel_event" || !message.event) return;
      upsertChannelEvent(message.event);
      const channelId = String(
        message.channel?.id || message.event.binding_id || "",
      );
      const viewingThis =
        surface.kind === "channel" && surface.id === channelId;
      if (viewingThis) {
        setSurface((current) => ({
          ...current,
          threadKey: String(message.event.thread_key || ""),
        }));
        const status = message.event.status;
        if (["queued", "running"].includes(status) && message.event.run_id) {
          if (activeRunRef.current?.id !== message.event.run_id) {
            setActiveRun({ id: message.event.run_id });
            setPhase("running");
            setRunDetail("Live from your phone…");
          }
        }
        if (status === "responded" || status === "stored") {
          finishRun("idle", "Phone reply delivered.");
        }
        if (status === "failed") {
          finishRun("error", message.event.error || "Remote turn failed");
        }
      } else if (message.event.status === "queued") {
        const key = `channel:${channelId}:${message.event.thread_key || ""}`;
        setUnread((current) => ({
          ...current,
          [key]: (current[key] || 0) + 1,
        }));
        showToast(`New ${message.channel?.kind || "channel"} message`);
      }
    },
    [
      surface.kind,
      surface.id,
      upsertChannelEvent,
      finishRun,
      showToast,
      loadBots,
      loadGroups,
    ],
  );

  useWebSocket(
    useCallback(() => (marketing ? null : wsUrl("/ws/live")), [marketing]),
    onLiveMessage,
    setConnected,
  );

  // ---- Data loading ----------------------------------------------------

  const loadManagement = useCallback(async () => {
    if (!selectedBot) return;
    if (marketing) {
      setManagement(demoManagementData());
      setChannels([DEMO_CHANNEL]);
      setChannelEvents(DEMO_CHANNEL_EVENTS);
      return;
    }
    // Generation guard: a slow response for a previously selected bot must
    // never overwrite the fresh bot's panel (or wipe a Safety edit in flight).
    const botName = selectedBot.name;
    const stillCurrent = () => selectedBotRef.current?.name === botName;
    try {
      const [
        policy,
        routines,
        plugins,
        bindings,
        audit,
        delegations,
        codingExecutions,
        channelList,
        events,
        memory,
        facts,
      ] = await Promise.all([
        api.policy(botName),
        api.routines(),
        api.plugins(),
        api.botPlugins(botName),
        api.audit(botName),
        api.delegations(),
        api.codingExecutions(),
        api.channels(botName),
        api.channelEvents(),
        api.memory(botName),
        api.memoryFacts(botName),
      ]);
      if (!stillCurrent()) return;
      setManagement({
        policy: policy as Policy,
        routines: routines as Routine[],
        plugins: plugins as Plugin[],
        bindings: bindings as import("./types").BotPluginBinding[],
        audit: audit as AuditItem[],
        delegations: delegations as DelegationPlan[],
        codingExecutions: codingExecutions as CodingExecution[],
        channels: channelList as Channel[],
        channelEvents: events as ChannelEvent[],
        memoryRecords: memory.events || [],
        memoryFacts: facts.facts || [],
      });
      setChannels(channelList as Channel[]);
      setChannelEvents(events as ChannelEvent[]);
    } catch (error) {
      showToast(
        (error as Error).message || "Could not load bot controls",
        true,
      );
    }
  }, [selectedBot, showToast, marketing]);

  const loadInteractions = useCallback(async () => {
    if (!selectedBot) return;
    if (marketing) {
      setPermissions([]);
      return;
    }
    try {
      const items = await api.interactions(selectedBot.name);
      setPermissions(
        items.map((item: Interaction) => ({
          id: item.id,
          title: item.title,
          runId: item.run_id,
          requestId: item.request_id,
          toolName: item.tool_name,
          source: item.actor,
        })),
      );
    } catch {
      // Background poll — stays silent AND keeps stale state on failure. The
      // sidebar's Offline indicator owns connection state; a toast every 2.5s
      // during a daemon blip is how you get stacked "Failed to fetch" banners,
      // and clearing approvals mid-blip could hide a pending decision.
    }
  }, [selectedBot, marketing]);

  const loadThread = useCallback(async () => {
    if (!selectedBot) return;
    if (marketing) {
      setHistoryTurns([]);
      setParts(DEMO_THREADS[selectedBot.name] ?? []);
      return;
    }
    const botName = selectedBot.name;
    try {
      const data = await api.history(botName);
      // A bot switch (or reconnect heal racing a live run) resolving late
      // must not wipe the current thread — especially mid-run optimistic
      // parts. While a run is in flight the stream owns the thread.
      if (selectedBotRef.current?.name !== botName) return;
      if (activeRunRef.current !== null) return;
      setHistoryTurns(normalizeHistory(data));
      setParts([]);
    } catch (error) {
      setHistoryTurns([]);
      setParts([]);
      showToast(
        (error as Error).message || "Could not load this conversation",
        true,
      );
    }
  }, [selectedBot, showToast, marketing]);

  const selectSurface = useCallback(
    (next: Surface) => {
      if (window.innerWidth <= 900) setSidebarOpen(false);
      if (activeRunRef.current !== null || queuedRef.current.length > 0) {
        // Durable runs keep executing headless and land in history — say so
        // instead of silently abandoning the stream.
        showToast(
          "Run continues in the background — come back for the result.",
          false,
        );
      }
      setSurface(next);
      setActiveRun(null);
      setQueuedRuns([]);
      setPhase("idle");
      setRunDetail("");
      if (next.kind === "channel") {
        const key = `channel:${next.id}:${next.threadKey || ""}`;
        setUnread((current) => ({ ...current, [key]: 0 }));
      }
    },
    [showToast],
  );

  const selectBotByName = useCallback(
    (name: string) => {
      const bot = bots.find((item) => item.name === name);
      if (!bot) return;
      if (window.innerWidth <= 900) setSidebarOpen(false);
      if (activeRunRef.current !== null || queuedRef.current.length > 0) {
        showToast(
          "Run continues in the background — come back for the result.",
          false,
        );
      }
      setActiveRun(null);
      setQueuedRuns([]);
      setSelectedBot(bot);
      setActiveGroupId(null);
      setSurface({ kind: "local" });
      setPhase("idle");
      setRunDetail("");
      setTimeline([]);
      setInspectPinned(false);
      setWorkspace("conversation");
      const url = new URL(location.href);
      url.searchParams.set("bot", bot.name);
      history.replaceState({}, "", url);
    },
    [bots, showToast],
  );

  useEffect(() => {
    if (!selectedBot) return;
    void loadThread();
    void loadManagement();
    void loadInteractions();
    const timer = window.setInterval(() => void loadInteractions(), 2500);
    return () => window.clearInterval(timer);
  }, [selectedBot, loadThread, loadManagement, loadInteractions]);

  useEffect(() => {
    void loadBots();
    void loadGroups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Safety net only: the live socket pushes roster changes instantly, so this
  // slow poll exists purely for writers outside the daemon (e.g. the CLI
  // editing the store directly). Quiet, skips hidden tabs, announces nothing
  // new on its own — loadBots toasts genuine newcomers whenever they appear.
  useEffect(() => {
    if (marketing) return;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void loadBots({ quiet: true });
      void loadGroups();
    }, 30000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketing]);

  // Sidebar inbox badge: how many approval asks are waiting on the operator.
  // Quiet poll — the Work inbox page owns error display and decisions.
  useEffect(() => {
    if (marketing) return;
    let alive = true;
    const load = async () => {
      try {
        const items = await api.interactions(undefined, "pending");
        if (alive) setPendingApprovals(items.length);
      } catch {
        // Keep the last count on failure; a badge must never flap to zero.
      }
    };
    void load();
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void load();
    }, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [marketing]);

  // Self-heal on reconnect: the daemon just came back (deploy, restart,
  // network blip) after we saw it go away. Re-read everything quietly so a
  // frozen screen repopulates without a manual reload. Skips the initial
  // connect (prev === null) — first paint already loads all of this.
  const prevConnectedRef = useRef<boolean | null>(null);
  useEffect(() => {
    const prev = prevConnectedRef.current;
    prevConnectedRef.current = connected;
    if (prev === false && connected && !marketing && selectedBot) {
      void loadThread();
      void loadManagement();
      void loadBots({ quiet: true });
      void loadGroups();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, marketing, selectedBot]);

  const openGroup = useCallback((groupId: string) => {
    if (window.innerWidth <= 900) setSidebarOpen(false);
    setActiveGroupId(groupId);
    setWorkspace("conversation");
    setInspectPinned(false);
  }, []);

  // ---- Turns -----------------------------------------------------------

  const submitTurn = useCallback(
    async (message: string) => {
      if (!selectedBot || surface.kind === "channel") return;
      if (marketing) {
        const full = demoResponseFor(message);
        setParts((current) => [
          ...current,
          { type: "user", text: message },
          { type: "assistant-text", text: "", streaming: true },
        ]);
        setPhase("starting");
        setRunDetail("Creating a demo run…");
        setActiveRun({ id: "demo-run" });
        window.setTimeout(() => {
          setPhase("running");
          setRunDetail("Kiro is working in this bot's persistent session.");
          addTimeline("tool", "filesystem.read · README.md");
        }, 450);
        let index = 0;
        if (demoStreamRef.current) window.clearInterval(demoStreamRef.current);
        demoStreamRef.current = window.setInterval(() => {
          index += 3;
          const text = full.slice(0, index);
          const streaming = index < full.length;
          setParts((current) => {
            const head = current.slice(0, -1);
            return [...head, { type: "assistant-text", text, streaming }];
          });
          if (!streaming) {
            if (demoStreamRef.current)
              window.clearInterval(demoStreamRef.current);
            demoStreamRef.current = null;
            finishRun("idle", "Run complete");
            addTimeline("complete", "Run completed");
          }
        }, 28);
        return;
      }
      const roster = bots.map((bot) => bot.name);
      setParts((current) => [
        ...current,
        { type: "user", text: message, mentions: roster },
      ]);

      // @mention routing: "@nick do X" hands the turn to nick's own session
      // while the transcript stays on this thread for everyone reading it.
      const mentionMatch = message.match(/(?:^|\s)@([A-Za-z0-9_\-.]+)/);
      const mentionName = mentionMatch?.[1].toLowerCase();
      const mentionBot =
        mentionName && mentionName !== selectedBot.name.toLowerCase()
          ? bots.find((bot) => bot.name.toLowerCase() === mentionName)
          : undefined;
      if (mentionBot) {
        const queueBehindMention = activeRunRef.current !== null;
        if (!queueBehindMention) {
          setPhase("starting");
          setRunStartedAt(Date.now());
        }
        try {
          const data = await api.submitTurn(mentionBot.name, message);
          const id = data.run_id || data.id || data.run?.id;
          if (!id) throw new Error("The server did not return a run ID.");
          if (queueBehindMention) {
            setQueuedRuns((current) => [...current, String(id)]);
            addTimeline("info", `Mention queued for ${mentionBot.name}`);
            showToast(`Queued — @${mentionBot.name} picks it up next`);
            return;
          }
          if (activeRunRef.current !== null) {
            // A concurrent submit attached a run while we awaited — queue
            // behind it instead of orphaning its stream with setActiveRun.
            setQueuedRuns((current) => [...current, String(id)]);
            addTimeline("info", `Mention queued for ${mentionBot.name}`);
            showToast(`Queued — @${mentionBot.name} picks it up next`);
            return;
          }
          setActiveRun({ id: String(id) });
          setPhase("running");
          setRunDetail(`@${mentionBot.name} is handling this mention.`);
          setRunStartedAt(Date.now());
          addTimeline("info", `Mention routed to ${mentionBot.name}`);
          showToast(`@${mentionBot.name} is on it`);
        } catch (error) {
          const detail = (error as Error).message;
          setParts((current) => [...current, { type: "error", text: detail }]);
          if (!queueBehindMention) finishRun("error", detail);
          showToast(detail || "Could not reach the mentioned bot", true);
        }
        return;
      }

      const queueBehind = activeRunRef.current !== null;
      if (!queueBehind) {
        setPhase("starting");
        setRunDetail("Creating a persistent run…");
        setRunStartedAt(Date.now());
      }
      try {
        const data = await api.submitTurn(selectedBot.name, message);
        const id = data.run_id || data.id || data.run?.id;
        if (!id) throw new Error("The server did not return a run ID.");
        if (queueBehind) {
          const position = queuedRef.current.length + 1;
          setQueuedRuns((current) => [...current, String(id)]);
          addTimeline("info", `Message queued (#${position} in line)`);
          showToast(`Queued #${position} — runs after the current turn`);
          return;
        }
        if (activeRunRef.current !== null) {
          // A concurrent submit (double-Enter) attached a run while we
          // awaited. Queue behind it — setActiveRun here would unmount its
          // stream and lose its chunks/terminal while it keeps running.
          const position = queuedRef.current.length + 1;
          setQueuedRuns((current) => [...current, String(id)]);
          addTimeline("info", `Message queued (#${position} in line)`);
          showToast(`Queued #${position} — runs after the current turn`);
          return;
        }
        setActiveRun({ id: String(id) });
        setPhase("running");
        setRunDetail("Working in this bot's persistent session.");
        setRunStartedAt(Date.now());
      } catch (error) {
        const message2 = (error as Error).message;
        setParts((current) => [...current, { type: "error", text: message2 }]);
        showToast(message2 || "Could not start run", true);
        if (queueBehind) {
          // A queued submission failing must NOT tear down the active run —
          // finishRun() would unmount its stream and orphan the queue.
          return;
        }
        finishRun("error", message2);
        // Nothing is active now; if a queued run exists, keep the thread moving.
        attachNextQueued();
      }
    },
    [
      selectedBot,
      surface.kind,
      finishRun,
      showToast,
      marketing,
      addTimeline,
      attachNextQueued,
      bots,
    ],
  );

  /** Attach an already-submitted run (retry/fork) to this thread. */
  const launchSubmittedRun = useCallback(
    (id: string, detail: string) => {
      if (activeRunRef.current !== null) {
        const position = queuedRef.current.length + 1;
        setQueuedRuns((current) => [...current, String(id)]);
        addTimeline("info", `${detail} (queued #${position})`);
        showToast(`Queued #${position} — runs after the current turn`);
        return;
      }
      setActiveRun({ id: String(id) });
      setPhase("running");
      setRunDetail(detail);
      setRunStartedAt(Date.now());
    },
    [addTimeline, showToast],
  );

  /** Retry a durable turn verbatim. The original prompt stays in history. */
  const retryTurn = useCallback(
    async (turnId: number) => {
      if (!selectedBot || marketing) return;
      const queueBehind = activeRunRef.current !== null;
      if (!queueBehind) {
        setPhase("starting");
        setRunDetail("Retrying turn…");
        setRunStartedAt(Date.now());
      }
      try {
        const data = await api.retryTurn(selectedBot.name, turnId);
        const id = data.run_id || data.id || data.run?.id;
        if (!id) throw new Error("The server did not return a run ID.");
        addTimeline("info", `Retrying turn #${turnId}`);
        launchSubmittedRun(String(id), "Retrying turn…");
      } catch (error) {
        const detail = (error as Error).message;
        setParts((current) => [...current, { type: "error", text: detail }]);
        showToast(detail || "Could not retry turn", true);
        if (queueBehind) return;
        finishRun("error", detail);
        attachNextQueued();
      }
    },
    [
      selectedBot,
      marketing,
      finishRun,
      showToast,
      addTimeline,
      attachNextQueued,
      launchSubmittedRun,
    ],
  );

  /** Load a turn's prompt into the composer for edit & rerun. */
  const editTurn = useCallback(
    (prompt: string) => {
      setComposerDraft({ text: prompt, nonce: Date.now() });
      showToast(
        "Prompt loaded in the composer — edit and send to rerun.",
        false,
      );
    },
    [showToast],
  );

  /** Fork a turn onto another bot with a handoff bundle, then go watch it. */
  const forkTurn = useCallback(
    async (turnId: number, toBot: string) => {
      if (!selectedBot || marketing) return;
      try {
        const data = await api.forkTurn(selectedBot.name, turnId, toBot);
        const id = data.run_id || data.id || data.run?.id;
        if (!id) throw new Error("The server did not return a run ID.");
        // Prefetch the target thread BEFORE switching selection: the
        // post-switch loadThread skips while a run is active, so without
        // this the target would render the source's stale parts.
        let turns: HistoryTurn[] = [];
        try {
          turns = normalizeHistory(await api.history(toBot));
        } catch {
          turns = [];
        }
        showToast(`Forked to @${toBot} with full context`, false);
        addTimeline("info", `Turn #${turnId} forked to ${toBot}`);
        selectBotByName(toBot);
        setHistoryTurns(turns);
        setParts([]);
        setActiveRun({ id: String(id) });
        setPhase("running");
        setRunDetail(`Continuing forked turn…`);
        setRunStartedAt(Date.now());
      } catch (error) {
        showToast((error as Error).message || "Could not fork turn", true);
      }
    },
    [selectedBot, marketing, showToast, addTimeline, selectBotByName],
  );

  const continueHandoff = useCallback(
    async (toBot: string, prompt: string) => {
      if (!selectedBot) throw new Error("Choose a source bot first.");
      if (marketing) throw new Error("Handoffs need a local daemon.");
      if (activeRunRef.current)
        throw new Error(
          "Wait for the current run to finish before handing it off.",
        );
      const sourceName = selectedBot.name;
      const data = await api.submitTurn(toBot, prompt);
      const id = data.run_id || data.id || data.run?.id;
      if (!id) throw new Error("The server did not return a run ID.");
      let turns: HistoryTurn[] = [];
      try {
        turns = normalizeHistory(await api.history(toBot));
      } catch {
        // The live response will populate this new target thread.
      }
      selectBotByName(toBot);
      setHistoryTurns(turns);
      setParts([]);
      setActiveRun({ id: String(id) });
      setPhase("running");
      setRunDetail(`Continuing handoff from @${sourceName}…`);
      setRunStartedAt(Date.now());
      addTimeline("info", `Handoff from @${sourceName} to @${toBot}`);
    },
    [selectedBot, marketing, selectBotByName, addTimeline],
  );

  const cancelRun = useCallback(async () => {
    if (!activeRun) return;
    if (marketing) {
      if (demoStreamRef.current) window.clearInterval(demoStreamRef.current);
      demoStreamRef.current = null;
      finishRun("idle", "Run cancelled");
      return;
    }
    const previousPhase = phase;
    const runId = activeRun.id;
    setPhase("stopping");
    setRunDetail("Requesting a clean stop…");
    // If no terminal envelope arrives (dead socket, missed poll), unstick the
    // composer after a grace period. A late terminal afterwards is harmless:
    // finishRun is idempotent and the queue was already drained here.
    const watchdog = window.setTimeout(() => {
      if (activeRunRef.current?.id === runId) {
        finishRun("idle", "Stop requested — the run is winding down.");
        attachNextQueued();
      }
    }, 12000);
    try {
      await api.cancelRun(runId);
    } catch (error) {
      window.clearTimeout(watchdog);
      setPhase(previousPhase);
      setRunDetail("");
      showToast((error as Error).message || "Could not cancel run", true);
    }
  }, [activeRun, phase, showToast, marketing, finishRun, attachNextQueued]);

  /** Mid-conversation model switch — the daemon reports whether it went live. */
  const switchModel = useCallback(
    async (model: string): Promise<boolean> => {
      if (!selectedBot) return false;
      if (marketing) {
        showToast(
          "Demo preview — model switching needs a local daemon.",
          false,
        );
        return false;
      }
      try {
        const data = await api.setBotModel(selectedBot.name, model);
        setSelectedBot((bot) => (bot ? { ...bot, model } : bot));
        setBots((list) =>
          list.map((bot) =>
            bot.name === selectedBot.name ? { ...bot, model } : bot,
          ),
        );
        showToast(
          data.applied_live
            ? `Model switched to ${model || "Default model"} — live session updated.`
            : `Model set to ${model || "Default model"} — applies from the next run.`,
        );
        addTimeline(
          "info",
          `Model → ${model || "default"}${data.applied_live ? " (live)" : " (next run)"}`,
        );
        return true;
      } catch (error) {
        showToast((error as Error).message || "Could not switch model", true);
        return false;
      }
    },
    [selectedBot, showToast, marketing, addTimeline],
  );

  /** Slash-command palette for the composer — type "/" to open it. */
  const botCommands = useMemo(
    () =>
      buildBotCommands({
        engine: selectedBot?.engine || "kiro",
        currentModel: selectedBot?.model,
        marketing,
        busy:
          phase === "running" || phase === "starting" || phase === "waiting",
        modelChoices: async () => {
          const engine = (selectedBot?.engine || "kiro").toLowerCase();
          const withDefault = (
            list: { id: string; label: string; detail?: string }[],
          ) => {
            if (selectedBot?.model) {
              list.unshift({
                id: "",
                label: "Default model",
                detail: "engine default",
              });
            }
            return list;
          };
          try {
            const data = await api.engines(engine);
            const list = (data.models || []).map((model) => ({
              id: model.id,
              label: model.label || model.id,
              detail:
                model.label && model.label !== model.id ? model.id : undefined,
            }));
            if (engine === "kiro" && list.length === 0) {
              return withDefault(
                KIRO_MODELS.filter((model) => model.id !== "__custom"),
              );
            }
            return withDefault(list);
          } catch {
            if (engine === "kiro") {
              return withDefault(
                KIRO_MODELS.filter((model) => model.id !== "__custom"),
              );
            }
            return [];
          }
        },
        onModel: (id) => void switchModel(id),
        onStop: () => void cancelRun(),
        onDialog: (name) => setDialog(name),
        onWorkflows: () => setWorkspace("workflows"),
        onInspect: () => setInspectPinned(true),
        onTheme: (theme) => applyTheme(theme),
      }),
    [selectedBot, marketing, phase, switchModel, cancelRun],
  );

  const decidePermission = useCallback(
    async (id: string, decision: "once" | "reject") => {
      if (marketing) {
        setPermissions((current) =>
          current.filter((permission) => permission.id !== id),
        );
        setParts((current) =>
          current.filter(
            (part) => !(part.type === "approval" && part.id === id),
          ),
        );
        setPhase("running");
        setRunDetail("Approval recorded. Continuing the run.");
        return;
      }
      const permission = permissions.find((item) => item.id === id);
      try {
        if (
          permission?.runId &&
          permission.requestId &&
          permission.id.length === 32
        ) {
          await api.decideInteraction(permission.id, decision);
        } else if (activeRun) {
          await api.decidePermission(
            activeRun.id,
            permission?.requestId || id,
            decision,
          );
        } else {
          throw new Error(
            "This approval is no longer attached to an active run.",
          );
        }
        setPermissions((current) =>
          current.filter((permission) => permission.id !== id),
        );
        setParts((current) =>
          current.filter(
            (part) => !(part.type === "approval" && part.id === id),
          ),
        );
        setPhase("running");
        setRunDetail("Approval recorded. Continuing the run.");
      } catch (error) {
        showToast(
          (error as Error).message || "Could not submit decision",
          true,
        );
      }
    },
    [activeRun, permissions, showToast],
  );

  // ---- Management actions ----------------------------------------------

  const guard = useCallback(
    async (action: () => Promise<unknown>, success?: string) => {
      if (marketing) {
        showToast(
          "Demo preview — run `uv run ari serve` locally to use this.",
          false,
        );
        return;
      }
      try {
        await action();
        if (success) showToast(success);
        await loadManagement();
      } catch (error) {
        showToast((error as Error).message, true);
      }
    },
    [loadManagement, showToast, marketing],
  );

  const workActions: WorkActions = useMemo(
    () => ({
      onNewRoutine: () => setDialog("routine"),
      onToggleRoutine: (routine: Routine) =>
        void guard(() =>
          api.patchRoutine(routine.id, { enabled: !routine.enabled }),
        ),
      onDeleteRoutine: (routine: Routine) =>
        void guard(() => api.deleteRoutine(routine.id)),
      onNewCoding: () => setDialog("coding"),
      onApproveCoding: (execution: CodingExecution) =>
        void guard(
          () => api.approveCodingExecution(execution.id, execution.version),
          "Verified handoff approved.",
        ),
      onCancelCoding: (execution: CodingExecution) =>
        void guard(() => api.cancelCodingExecution(execution.id)),
      onNewDelegation: () => setWorkspace("workflows"),
      onStartDelegation: (plan: DelegationPlan) =>
        void guard(() => api.startDelegation(plan.id)),
      onCancelDelegation: (plan: DelegationPlan) =>
        void guard(() => api.cancelDelegation(plan.id)),
      onNewChannel: () => setDialog("channel"),
      onCopyWebhook: (channel: Channel) => {
        const path = `/hooks/${channel.kind}/${encodeURIComponent(channel.id)}`;
        navigator.clipboard
          .writeText(`${location.origin}${path}`)
          .then(() => showToast("Webhook URL copied."))
          .catch(() => showToast("Could not copy the URL.", true));
      },
      onToggleChannel: (channel: Channel) =>
        void guard(() =>
          api.patchChannel(channel.id, { enabled: !channel.enabled }),
        ),
      onDeleteChannel: (channel: Channel) =>
        void guard(() => api.deleteChannel(channel.id)),
    }),
    [guard, showToast],
  );

  const safetyActions: SafetyActions = useMemo(
    () => ({
      onSavePolicy: async (policy: Policy) => {
        if (!selectedBot) return;
        await guard(
          () => api.savePolicy(selectedBot.name, policy),
          "Safety policy saved.",
        );
      },
      onNewPlugin: () => setDialog("plugin"),
      onDisconnectPlugin: (pluginId: string) => {
        if (!selectedBot) return;
        void guard(() => api.unbindPlugin(selectedBot.name, pluginId));
      },
      onUpdatePlugin: (pluginId, payload) => {
        if (!selectedBot) return;
        void guard(() =>
          api.updatePluginBinding(selectedBot.name, pluginId, payload),
        );
      },
    }),
    [guard, selectedBot],
  );

  useEffect(() => {
    if (marketing) return;
    if ((inspectTab !== "work" && workspace !== "workflows") || !selectedBot)
      return;
    const timer = window.setInterval(() => {
      void api
        .delegations()
        .then((plans) =>
          setManagement((c) => ({
            ...c,
            delegations: plans as DelegationPlan[],
          })),
        )
        .catch(() => undefined);
      void api
        .codingExecutions()
        .then((executions) =>
          setManagement((c) => ({
            ...c,
            codingExecutions: executions as CodingExecution[],
          })),
        )
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [inspectTab, selectedBot, workspace, marketing]);

  const changeTab = useCallback(
    (tab: InspectTab) => {
      setInspectTab(tab);
      setInspectPinned(true);
      if (tab !== "run") void loadManagement();
    },
    [loadManagement],
  );

  // ---- Derived -----------------------------------------------------------

  const busy =
    phase === "starting" ||
    phase === "running" ||
    phase === "waiting" ||
    phase === "stopping";
  const inspectOpen = Boolean(inspectPinned || permissions.length > 0);
  const localLive =
    phase === "running" || phase === "waiting" || phase === "starting";

  // Trailing run-is-alive indicator: the ghost narrates the run's stage while
  // it is in flight so a quiet stretch reads as "working", never "stuck".
  const thinkingNode =
    busy && surface.kind !== "channel" && !activeGroupId ? (
      <ThinkingGhost
        phase={phase}
        botName={selectedBot?.name || ""}
        detail={runDetail}
        startedAt={runStartedAt}
        queued={queuedRuns.length}
        hasOutput={parts.some(
          (part) =>
            part.type === "assistant-text" ||
            part.type === "reasoning" ||
            part.type === "tool",
        )}
      />
    ) : undefined;

  const channelLabel = useMemo(() => {
    if (surface.kind !== "channel") return "";
    const channel = channels.find((item) => item.id === surface.id);
    return channel?.kind === "telegram"
      ? "Telegram"
      : channel?.name || "Remote";
  }, [surface, channels]);

  // History turns render as actionable sections (retry/edit/fork); the live
  // buffer streams beneath them. Channel mirrors stay one flat section.
  const turnSections = useMemo<TurnSection[]>(() => {
    if (surface.kind === "channel") {
      return [
        {
          id: "channel",
          prompt: "",
          parts: channelToParts(surface, channelEvents, channelLabel),
        },
      ];
    }
    return historyTurns.map((turn, index) => ({
      id: `turn-${turn.id ?? index}`,
      turnId: turn.id,
      prompt: turnPrompt(turn),
      parts: mapTurnParts(turn, index),
    }));
  }, [surface, channelEvents, channelLabel, historyTurns]);

  const composerDisabled = !selectedBot || surface.kind === "channel";
  const activeGroup = useMemo(
    () => groups.find((group) => group.id === activeGroupId) || null,
    [groups, activeGroupId],
  );

  const closeDialog = useCallback(() => setDialog(null), []);
  const doneAndReload = useCallback(() => {
    if (marketing) {
      void loadManagement();
      return;
    }
    void loadManagement();
    void loadBots();
  }, [loadManagement, loadBots, marketing]);

  const dialogProps = {
    open: dialog !== null,
    onClose: closeDialog,
    bot: selectedBot,
    bots,
    onDone: doneAndReload,
  };

  return (
    <div className="app">
      <Sidebar
        bots={bots}
        selectedBot={selectedBot?.name ?? null}
        onSelectBot={selectBotByName}
        groups={groups}
        activeGroup={activeGroupId}
        onSelectGroup={openGroup}
        onNewGroup={() => setDialog("group")}
        channels={channels}
        channelEvents={channelEvents}
        surface={surface}
        onSelectSurface={selectSurface}
        unread={unread}
        inboxBadge={pendingApprovals}
        localLive={localLive}
        connected={connected}
        connectionLabel={marketing ? "Demo preview" : undefined}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onNewBot={() =>
          marketing
            ? showToast(
                "Demo preview — create bots with `uv run ari bot create`.",
                false,
              )
            : setDialog("bot")
        }
        workspace={workspace}
        onWorkspaceChange={(next) => {
          setActiveGroupId(null);
          setWorkspace(next);
          setInspectPinned(false);
          if (window.innerWidth <= 900) setSidebarOpen(false);
        }}
      />

      <main className="main">
        {sidebarOpen && (
          <button
            type="button"
            className="sidebar-backdrop"
            aria-label="Close sidebar"
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <header className="header">
          <div className="header-brand">
            <button
              type="button"
              className="hamburger"
              aria-label="Toggle sidebar"
              aria-pressed={sidebarOpen}
              aria-expanded={sidebarOpen}
              onClick={() => setSidebarOpen((open) => !open)}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden
              >
                <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
              </svg>
            </button>
            <button
              type="button"
              className="header-logo"
              aria-label="Back to landing page"
              onClick={onExit}
            >
              <AriGlyph size={20} finish="silver" />
            </button>
            {!activeGroupId && selectedBot && workspace === "conversation" && (
              <BotAvatar
                name={selectedBot.name}
                size={30}
                className="header-bot-avatar"
              />
            )}
            <span className="header-title">
              {activeGroupId
                ? activeGroup?.name || "Group chat"
                : workspace === "workflows"
                  ? "Workflows"
                  : workspace === "inbox"
                    ? "Work inbox"
                    : workspace === "tasks"
                      ? "Tasks"
                      : workspace === "plugins"
                        ? "Plugin Place"
                        : selectedBot
                          ? selectedBot.name
                          : "Choose a bot"}
            </span>
            {!activeGroupId && selectedBot && workspace === "conversation" && (
              <ModelSwitcher
                bot={selectedBot}
                onSwitch={switchModel}
                disabled={marketing}
              />
            )}
          </div>
          <div className="header-actions">
            <div className="header-desktop-actions">
              {!activeGroupId &&
                selectedBot &&
                workspace === "conversation" && (
                  <button
                    type="button"
                    className="workflow-launch"
                    onClick={() =>
                      marketing
                        ? showToast(
                            "Demo preview — handoffs need a local daemon.",
                            false,
                          )
                        : setDialog("handoff")
                    }
                  >
                    Handoff
                  </button>
                )}
              <span className="status-pill" data-state={phase}>
                <span className="status-dot" aria-hidden />
                {PHASE_TITLE[phase]}
              </span>
              {marketing && (
                <span
                  className="status-pill preview"
                  title="Interactive preview — no live backend"
                >
                  Preview
                </span>
              )}
            </div>
            <button
              type="button"
              className={`icon-btn${inspectOpen ? " active" : ""}`}
              aria-label="Inspect run and bot details"
              aria-pressed={inspectOpen}
              onClick={() => setInspectPinned(!inspectPinned)}
            >
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                aria-hidden
              >
                <rect x="3" y="4" width="18" height="16" rx="2" />
                <path d="M14 4v16M7 8h4M7 12h4M7 16h4" strokeLinecap="round" />
              </svg>
              <span className="header-action-label">Inspect</span>
            </button>
            <div className="header-more" ref={headerMoreRef}>
              <button
                type="button"
                className="header-more-trigger"
                aria-label="More actions"
                aria-controls="header-more-menu"
                aria-expanded={headerMoreOpen}
                onClick={() => setHeaderMoreOpen((open) => !open)}
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  aria-hidden
                >
                  <circle cx="5" cy="12" r="1.6" />
                  <circle cx="12" cy="12" r="1.6" />
                  <circle cx="19" cy="12" r="1.6" />
                </svg>
              </button>
              {headerMoreOpen && (
                <div
                  id="header-more-menu"
                  className="header-more-menu"
                  aria-label="More actions"
                >
                  {!activeGroupId &&
                    selectedBot &&
                    workspace === "conversation" && (
                      <button
                        type="button"
                        onClick={() => {
                          setHeaderMoreOpen(false);
                          marketing
                            ? showToast(
                                "Demo preview — handoffs need a local daemon.",
                                false,
                              )
                            : setDialog("handoff");
                        }}
                      >
                        Handoff to another bot
                      </button>
                    )}
                  <div className="header-more-nav">
                    <button
                      type="button"
                      onClick={() => {
                        setHeaderMoreOpen(false);
                        setActiveGroupId(null);
                        setInspectPinned(false);
                        setWorkspace("workflows");
                      }}
                    >
                      Open workflows
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setHeaderMoreOpen(false);
                        setActiveGroupId(null);
                        setInspectPinned(false);
                        setWorkspace("tasks");
                      }}
                    >
                      Open tasks
                    </button>
                  </div>
                  <div className="header-more-status" role="status">
                    <span className="status-dot" aria-hidden />
                    {PHASE_TITLE[phase]}
                    {marketing ? " · Preview" : ""}
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        {activeGroupId ? (
          <GroupChat
            key={activeGroupId}
            groupId={activeGroupId}
            bots={bots}
            marketing={marketing}
            onBack={() => setActiveGroupId(null)}
            onChanged={() => void loadGroups()}
            onDeleted={() => {
              setActiveGroupId(null);
              void loadGroups();
            }}
          />
        ) : workspace === "inbox" ? (
          <InboxPage
            demoMode={marketing}
            onOpenTask={(id) => {
              setInboxTaskId(id);
              setActiveGroupId(null);
              setInspectPinned(false);
              setWorkspace("tasks");
              if (window.innerWidth <= 900) setSidebarOpen(false);
            }}
            onOpenWorkflow={(id) => {
              setInboxWorkflowId(id || null);
              setActiveGroupId(null);
              setInspectPinned(false);
              setWorkspace("workflows");
              if (window.innerWidth <= 900) setSidebarOpen(false);
            }}
            onOpenBot={selectBotByName}
            onOpenChannel={(event, botName) => {
              if (botName) selectBotByName(botName);
              setActiveGroupId(null);
              setWorkspace("conversation");
              selectSurface({
                kind: "channel",
                id: event.binding_id,
                threadKey: event.thread_key,
              });
            }}
            onCreateTask={() => {
              if (marketing)
                showToast("Demo preview — tasks need a local daemon.", false);
              else setDialog("task");
            }}
            showToast={showToast}
          />
        ) : workspace === "workflows" ? (
          <WorkflowPlayground
            bots={bots}
            plans={management.delegations}
            initialPlanId={inboxWorkflowId}
            demoMode={marketing}
            onRefresh={doneAndReload}
            onStart={(plan) =>
              void guard(
                () => api.startDelegation(plan.id),
                "Workflow started.",
              )
            }
            onCancel={(plan) =>
              void guard(
                () => api.cancelDelegation(plan.id),
                "Workflow cancelled.",
              )
            }
          />
        ) : workspace === "tasks" ? (
          <TaskBoard
            initialTaskId={inboxTaskId}
            demoMode={marketing}
            onNewTask={() =>
              marketing
                ? showToast("Demo preview — tasks need a local daemon.", false)
                : setDialog("task")
            }
            showToast={showToast}
          />
        ) : workspace === "plugins" ? (
          <PluginPlaceBoard
            bots={bots}
            demoMode={marketing}
            onBackToChat={() => setWorkspace("conversation")}
            showToast={showToast}
          />
        ) : (
          <>
            <div
              ref={containerRef}
              className="thread-scroll"
              onScroll={onScroll}
            >
              <Thread
                sections={turnSections}
                liveParts={parts}
                emptyEyebrow={
                  surface.kind === "channel"
                    ? `${channelLabel || "CHANNEL"} · MESSAGE RELAY`
                    : selectedBot?.name.trim().toLowerCase() === "chief"
                      ? "Ari · CONTROL ROOM"
                      : selectedBot
                        ? `${selectedBot.name.toUpperCase()} · AGENT WORKSPACE`
                        : "Ari · GET STARTED"
                }
                emptyGreeting={
                  surface.kind === "channel"
                    ? `Your ${channelLabel || "channel"} is connected.`
                    : selectedBot
                      ? selectedBot.name.trim().toLowerCase() === "chief"
                        ? "Give the fleet a goal."
                        : `Let's make progress with ${selectedBot.name}.`
                      : "Create a bot to begin"
                }
                emptyDescription={
                  surface.kind === "channel"
                    ? "Messages from this channel will appear here. Send a message from your connected app to start a conversation."
                    : selectedBot?.name.trim().toLowerCase() === "chief"
                      ? "Tell Chief what you want done. Follow handoffs, activity, and approvals from one place."
                      : selectedBot
                        ? "Give your bot a clear task, then steer or review its work as it goes."
                        : "Create your first bot, then give it a task in plain language."
                }
                botName={selectedBot?.name}
                thinking={thinkingNode}
                onRetry={(turnId) => void retryTurn(turnId)}
                onEdit={(prompt) => editTurn(prompt)}
                onFork={(turnId, toBot) => void forkTurn(turnId, toBot)}
                forkBots={bots
                  .filter((bot) => bot.name !== selectedBot?.name)
                  .map((bot) => bot.name)}
                suggestions={
                  surface.kind === "channel" || !selectedBot
                    ? []
                    : selectedBot.name.trim().toLowerCase() === "chief"
                      ? CHIEF_SUGGESTIONS
                      : SUGGESTIONS
                }
                onSuggestion={(text) => void submitTurn(text)}
                onApproval={(id, decision) =>
                  void decidePermission(id, decision)
                }
              />
            </div>

            {!stuck &&
              (parts.length > 0 ||
                turnSections.some((section) => section.parts.length > 0)) && (
                <button
                  type="button"
                  className="jump-latest"
                  onClick={() => scrollToLatest()}
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    aria-hidden
                  >
                    <path
                      d="M12 5v14M19 12l-7 7-7-7"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  Jump to latest
                </button>
              )}

            <Composer
              disabled={composerDisabled}
              busy={busy}
              hint={
                surface.kind === "channel"
                  ? "This view follows the live remote thread."
                  : selectedBot?.model ||
                    selectedBot?.agent ||
                    selectedBot?.cwd ||
                    "Select a bot to begin"
              }
              mirrorNote={surface.kind === "channel"}
              placeholder={
                selectedBot
                  ? `Message ${selectedBot.name}… (or @another-bot)`
                  : "Select a bot to begin"
              }
              commands={botCommands}
              members={
                surface.kind === "channel"
                  ? undefined
                  : bots
                      .filter((bot) => bot.name !== selectedBot?.name)
                      .map((bot) => bot.name)
              }
              onSubmit={(message) => void submitTurn(message)}
              onStop={() => void cancelRun()}
              draft={composerDraft}
            />
          </>
        )}
      </main>

      <InspectPanel
        open={inspectOpen}
        tab={inspectTab}
        onTab={changeTab}
        onClose={() => setInspectPinned(false)}
        inspectTitle={
          selectedBot?.name ? `Activity · ${selectedBot.name}` : "Activity"
        }
        phase={phase}
        runDetail={runDetail}
        permissions={permissions}
        onDecide={(id, decision) => void decidePermission(id, decision)}
        timeline={timeline}
        management={management}
        workActions={workActions}
        safetyActions={safetyActions}
        hasBot={Boolean(selectedBot)}
        bot={selectedBot}
        runStartedAt={runStartedAt}
        queue={queuedRuns.length}
        onSwitchModel={switchModel}
        switchingDisabled={marketing}
        onHandoff={() => setDialog("handoff")}
        onStopRun={() => void cancelRun()}
        usageRefreshKey={usageRefreshKey}
        showToast={showToast}
        onFactsChanged={() => void loadManagement()}
      />

      {dialog === "bot" && <CreateBotDialog {...dialogProps} />}
      {dialog === "group" && (
        <CreateGroupDialog
          {...dialogProps}
          onCreated={(groupId) => openGroup(groupId)}
        />
      )}
      {dialog === "routine" && <RoutineDialog {...dialogProps} />}
      {dialog === "plugin" && <PluginDialog {...dialogProps} />}
      {dialog === "channel" && <ChannelDialog {...dialogProps} />}
      {dialog === "coding" && <CodingDialog {...dialogProps} />}
      {dialog === "task" && <TaskDialog {...dialogProps} />}
      {dialog === "handoff" && (
        <HandoffDialog
          open
          onClose={closeDialog}
          bot={selectedBot}
          bots={bots}
          onDone={doneAndReload}
          onContinue={continueHandoff}
        />
      )}

      {activeRun && (
        <RunStream
          key={activeRun.id}
          run={activeRun}
          onEvent={handleStreamEvent}
        />
      )}
    </div>
  );
}

type View = "landing" | "engineering" | "console" | "setup";

function resolveView(): View {
  if (isDemoParam) return "console";
  const params = new URLSearchParams(location.search);
  const setupComplete =
    localStorage.getItem("ari_setup_complete") === "1" ||
    localStorage.getItem("kyn_setup_complete") === "1";
  if (params.get("mobile") === "1") return "console";
  if (params.get("desktop") === "1") {
    return setupComplete ? "console" : "setup";
  }
  if (params.get("setup") === "1" && !setupComplete) {
    return "setup";
  }
  if (isMarketingDeploy) {
    if (location.hash.includes("console")) return "console";
    if (location.hash.includes("engineering")) return "engineering";
    return "landing";
  }
  if (new URLSearchParams(location.search).has("bot")) return "console";
  if (location.hash.includes("console")) return "console";
  if (location.hash.includes("engineering")) return "engineering";
  return "landing";
}

export function App() {
  return (
    <ToastProvider>
      <AppShell />
    </ToastProvider>
  );
}

function AppShell() {
  const [view, setView] = useState<View>(resolveView);
  const { clearToasts } = useToast();

  useEffect(() => {
    const onHashChange = () => setView(resolveView());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    clearToasts();
    const scroller = document.querySelector(".ed") as HTMLElement | null;
    scroller?.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [view, clearToasts]);

  const enterConsole = useCallback(() => {
    history.replaceState(null, "", "#console");
    setView("console");
  }, []);

  const openEngineering = useCallback(() => {
    history.replaceState(null, "", "#engineering");
    setView("engineering");
  }, []);

  const enterDemo = useCallback(() => {
    history.replaceState(null, "", "?demo=1#console");
    setView("console");
  }, []);

  const finishSetup = useCallback(() => {
    localStorage.setItem("ari_setup_complete", "1");
    history.replaceState(
      null,
      "",
      `${location.pathname}${location.search}#console`,
    );
    setView("console");
  }, []);

  const exitToLanding = useCallback(() => {
    if (new URLSearchParams(location.search).get("desktop") === "1") {
      history.replaceState(
        null,
        "",
        `${location.pathname}${location.search}#console`,
      );
      setView("console");
      return;
    }
    const url = new URL(location.href);
    url.hash = "";
    url.search = "";
    history.replaceState(null, "", `${url.pathname}${url.search}`);
    setView("landing");
  }, []);

  return (
    <>
      {view === "setup" ? (
        <SetupWizard onContinue={finishSetup} />
      ) : view === "console" ? (
        <ControlRoom onExit={exitToLanding} />
      ) : view === "engineering" ? (
        <EngineeringPage
          onEnterConsole={enterConsole}
          onBackToLanding={exitToLanding}
        />
      ) : (
        <LandingPage
          onEnterConsole={enterConsole}
          onOpenEngineering={openEngineering}
          onTryDemo={enterDemo}
        />
      )}
    </>
  );
}

export default App;
