import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "./api";
import { wsUrl, useWebSocket } from "./hooks/useWebSocket";
import { ToastProvider, useToast } from "./hooks/useToast";
import { useTheme, type Theme } from "./lib/theme";
import { useStickToBottom } from "./lib/useStickToBottom";
import { isMarketingDeploy } from "./lib/deploy";
import EngineeringPage from "./pages/EngineeringPage";
import LandingPage from "./pages/LandingPage";
import { KiroGlyph } from "./components/KiroGlyph";
import { Thread } from "./components/chat/Thread";
import type { Part } from "./components/chat/Message";
import { Composer } from "./components/chat/Composer";
import { Sidebar } from "./components/Sidebar";
import { WorkflowPlayground } from "./components/workflows/WorkflowPlayground";
import { InspectPanel, type InspectTab, type ManagementData } from "./components/inspect/InspectPanel";
import type { WorkActions } from "./components/inspect/WorkTab";
import type { SafetyActions } from "./components/inspect/SafetyTab";
import {
  ChannelDialog,
  CodingDialog,
  CreateBotDialog,
  PluginDialog,
  RoutineDialog,
} from "./components/dialogs/Dialogs";
import type {
  AuditItem,
  Bot,
  Channel,
  ChannelEvent,
  CodingExecution,
  DelegationPlan,
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

type DialogName = "bot" | "routine" | "plugin" | "channel" | "coding" | null;

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
  "Summarize what this repo does",
  "What changed here recently?",
  "Find TODOs and rank them by urgency",
  "Write tests for the riskiest module",
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
  return String(event.text || event.content || event.message || event.title || "");
}

function normalizeBots(data: unknown): Bot[] {
  const list = Array.isArray(data)
    ? data
    : ((data as Record<string, unknown>)?.bots as unknown[]) ||
      ((data as Record<string, unknown>)?.items as unknown[]) ||
      [];
  return list.filter(Boolean).map((bot) => (typeof bot === "string" ? { name: bot } : (bot as Bot)));
}

function normalizeHistory(data: unknown): HistoryTurn[] {
  if (Array.isArray(data)) return data as HistoryTurn[];
  const record = data as Record<string, unknown>;
  return ((record?.turns || record?.history || record?.items || []) as HistoryTurn[]) || [];
}

function mapHistoryToParts(turns: HistoryTurn[]): Part[] {
  const parts: Part[] = [];
  turns.forEach((turn, turnIndex) => {
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
      const kind = String(event.kind || storedEvent.kind || event.type || "event");
      const text = eventText(event);
      const key = `h-${turnIndex}-${eventIndex}`;
      if (kind === "text" || kind === "agent_message_chunk" || kind === "assistant") {
        buffer += text;
        sawText = true;
      } else if (kind === "thinking" || kind === "agent_thought_chunk") {
        if (text) parts.push({ type: "reasoning", id: key, text, running: false });
      } else if (kind.includes("tool")) {
        parts.push({
          type: "tool",
          id: key,
          title: String(event.title || text || "Tool activity"),
          status: "done",
        });
      }
    });
    if (sawText) parts.push({ type: "assistant-text", text: buffer });
  });
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
    .sort((a, b) => String(a.created_at ?? "").localeCompare(String(b.created_at ?? "")));
  const parts: Part[] = [];
  events.forEach((event, index) => {
    parts.push({ type: "channel", text: String(event.text || ""), label: channelLabel });
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

  const handleMessage = useCallback(
    (payload: unknown) => {
      const envelope = payload as StreamEnvelope;
      const id = eventId(envelope) || eventId(envelope.event);
      if (id > afterRef.current) afterRef.current = id;
      onEvent(envelope);
    },
    [onEvent],
  );

  useWebSocket(
    useCallback(() => wsUrl(`/ws/runs/${encodeURIComponent(run.id)}?after=${afterRef.current}`), [run.id]),
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
        if (status && ["complete", "completed", "cancelled", "failed", "error"].includes(status.toLowerCase())) {
          if (!cancelled) {
            onEvent({
              type: "terminal",
              run: {
                status: status === "failed" || status === "error" ? "failed" : status,
                error: typeof record.detail === "string" ? record.detail : undefined,
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
  const [theme, toggleTheme] = useTheme() as [Theme, () => void];

  const [bots, setBots] = useState<Bot[]>([]);
  const [selectedBot, setSelectedBot] = useState<Bot | null>(null);
  const [surface, setSurface] = useState<Surface>({ kind: "local" });
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [runDetail, setRunDetail] = useState("");
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const [parts, setParts] = useState<Part[]>([]);
  const [permissions, setPermissions] = useState<PermissionRequest[]>([]);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelEvents, setChannelEvents] = useState<ChannelEvent[]>([]);
  const [unread, setUnread] = useState<Record<string, number>>({});
  const [connected, setConnected] = useState(false);
  const [inspectPinned, setInspectPinned] = useState(false);
  const [inspectTab, setInspectTab] = useState<InspectTab>("run");
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900);
  const [dialog, setDialog] = useState<DialogName>(null);
  const [workspace, setWorkspace] = useState<"conversation" | "workflows">("conversation");

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
  });

  const timelineIdRef = useRef(0);
  const activeRunRef = useRef<ActiveRun | null>(null);
  activeRunRef.current = activeRun;

  const { containerRef, stuck, onScroll, bump, scrollToLatest } = useStickToBottom();

  useEffect(() => {
    bump();
  }, [parts, bump]);

  const addTimeline = useCallback((kind: TimelineEntry["kind"], detail: string) => {
    timelineIdRef.current += 1;
    const entry: TimelineEntry = {
      id: Date.now() * 1000 + timelineIdRef.current,
      kind,
      detail: detail || kind.replaceAll("_", " "),
      at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
    setTimeline((current) => [entry, ...current]);
  }, []);

  const finishRun = useCallback((nextPhase: RunPhase, detail: string) => {
    setPhase(nextPhase);
    setRunDetail(detail);
    setPermissions([]);
    setParts((current) => finalizeParts(current));
    setActiveRun(null);
  }, []);

  const receiveEvent = useCallback(
    (envelope: StreamEnvelope) => {
      if (envelope.type === "terminal") {
        const status = envelope.run?.status || "complete";
        if (status === "failed") {
          const message = envelope.run?.error || "Run failed";
          setParts((current) => [...finalizeParts(current), { type: "error", text: message }]);
          finishRun("error", message);
          addTimeline("error", message);
        } else {
          finishRun("idle", envelope.run?.stop_reason || (status === "cancelled" ? "Run cancelled" : "Run complete"));
          addTimeline("complete", "Run completed");
        }
        return;
      }
      if (envelope.type === "error" && !envelope.kind) {
        const detail = envelope.detail || "Live stream failed";
        setParts((current) => [...finalizeParts(current), { type: "error", text: detail }]);
        finishRun("error", detail);
        showToast(detail, true);
        return;
      }

      const raw = envelope.event || envelope.data || (envelope as unknown);
      const event = parseEvent(raw);
      const kind = String(event.kind || event.type || "event");
      const text = eventText(event);

      if (kind === "text" || kind === "agent_message_chunk" || kind === "assistant") {
        setParts((current) => {
          const last = current[current.length - 1];
          if (last?.type === "assistant-text") {
            const next = [...current];
            next[next.length - 1] = { ...last, text: last.text + text, streaming: true };
            return next;
          }
          return [...current, { type: "assistant-text", text, streaming: true }];
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
          return [...current, { type: "reasoning", id: crypto.randomUUID(), text, running: true }];
        });
      } else if (kind === "permission" || kind === "interaction_required") {
        const id = String(event.interaction_id || event.request_id || event.requestId || event.id || crypto.randomUUID());
        const requestId = String(event.request_id || event.requestId || "");
        setPhase("waiting");
        setRunDetail(String(event.title || "Kiro needs permission to continue."));
        setPermissions((current) =>
          current.some((item) => item.id === id)
            ? current
            : [...current, {
                id,
                title: String(event.title || ""),
                runId: activeRunRef.current?.id,
                requestId,
                toolName: String(event.tool_name || ""),
              }],
        );
        setParts((current) =>
          current.some((part) => part.type === "approval" && part.id === id)
            ? current
            : [...current, { type: "approval", id, title: String(event.title || "") }],
        );
        addTimeline("permission", String(event.title || "Permission requested"));
      } else if (kind.includes("tool")) {
        const title = String(event.title || text || "Tool activity");
        setParts((current) =>
          current.some((part) => part.type === "tool" && part.title === title)
            ? current
            : [...current, { type: "tool", id: crypto.randomUUID(), title, status: "done" as const }],
        );
        addTimeline("tool", title);
        if (activeRunRef.current) {
          setPhase((currentPhase) => (currentPhase === "waiting" ? currentPhase : "running"));
          setRunDetail(title);
        }
      } else if (kind === "complete" || kind === "done") {
        finishRun("idle", String(event.stop_reason || "Run complete"));
        addTimeline("complete", "Run completed");
      } else if (kind === "error" || kind === "failed") {
        const message = text || "The run failed";
        setParts((current) => [...finalizeParts(current), { type: "error", text: message }]);
        finishRun("error", message);
        addTimeline("error", message);
        showToast(message, true);
      }
    },
    [addTimeline, finishRun, showToast],
  );

  const handleStreamEvent = useCallback((envelope: StreamEnvelope) => receiveEvent(envelope), [receiveEvent]);

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
      if (message.type !== "channel_event" || !message.event) return;
      upsertChannelEvent(message.event);
      const channelId = String(message.channel?.id || message.event.binding_id || "");
      const viewingThis = surface.kind === "channel" && surface.id === channelId;
      if (viewingThis) {
        setSurface((current) => ({ ...current, threadKey: String(message.event.thread_key || "") }));
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
        setUnread((current) => ({ ...current, [key]: (current[key] || 0) + 1 }));
        showToast(`New ${message.channel?.kind || "channel"} message`);
      }
    },
    [surface.kind, surface.id, upsertChannelEvent, finishRun, showToast],
  );

  useWebSocket(useCallback(() => wsUrl("/ws/live"), []), onLiveMessage, setConnected);

  // ---- Data loading ----------------------------------------------------

  const loadManagement = useCallback(async () => {
    if (!selectedBot) return;
    try {
      const [policy, routines, plugins, bindings, audit, delegations, codingExecutions, channelList, events, memory] =
        await Promise.all([
          api.policy(selectedBot.name),
          api.routines(),
          api.plugins(),
          api.botPlugins(selectedBot.name),
          api.audit(selectedBot.name),
          api.delegations(),
          api.codingExecutions(),
          api.channels(selectedBot.name),
          api.channelEvents(),
          api.memory(selectedBot.name),
        ]);
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
      });
      setChannels(channelList as Channel[]);
      setChannelEvents(events as ChannelEvent[]);
    } catch (error) {
      showToast((error as Error).message || "Could not load bot controls", true);
    }
  }, [selectedBot, showToast]);

  const loadInteractions = useCallback(async () => {
    if (!selectedBot) return;
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
    } catch (error) {
      showToast((error as Error).message || "Could not load pending actions", true);
    }
  }, [selectedBot, showToast]);

  const loadThread = useCallback(async () => {
    if (!selectedBot) return;
    try {
      const data = await api.history(selectedBot.name);
      setParts(mapHistoryToParts(normalizeHistory(data)));
    } catch (error) {
      setParts([]);
      showToast((error as Error).message || "Could not load this conversation", true);
    }
  }, [selectedBot, showToast]);

  const selectSurface = useCallback(
    (next: Surface) => {
      setSurface(next);
      setActiveRun(null);
      setPhase("idle");
      setRunDetail("");
      if (next.kind === "channel") {
        const key = `channel:${next.id}:${next.threadKey || ""}`;
        setUnread((current) => ({ ...current, [key]: 0 }));
      }
    },
    [],
  );

  const selectBotByName = useCallback(
    (name: string) => {
      const bot = bots.find((item) => item.name === name);
      if (!bot) return;
      setActiveRun(null);
      setSelectedBot(bot);
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
    [bots],
  );

  useEffect(() => {
    if (!selectedBot) return;
    void loadThread();
    void loadManagement();
    void loadInteractions();
    const timer = window.setInterval(() => void loadInteractions(), 2500);
    return () => window.clearInterval(timer);
  }, [selectedBot, loadThread, loadManagement, loadInteractions]);

  const loadBots = useCallback(async () => {
    try {
      const data = await api.listBots();
      const list = normalizeBots(data);
      setBots(list);
      setConnected(true);
      const requested = new URLSearchParams(location.search).get("bot");
      const preferred = list.find((bot) => bot.name === requested);
      if (preferred) setSelectedBot(preferred);
    } catch (error) {
      setConnected(false);
      showToast((error as Error).message || "Could not load bots", true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadBots();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Turns -----------------------------------------------------------

  const submitTurn = useCallback(
    async (message: string) => {
      if (!selectedBot || activeRun || surface.kind === "channel") return;
      setParts((current) => [...current, { type: "user", text: message }]);
      setPhase("starting");
      setRunDetail("Creating a persistent Kiro run…");
      try {
        const data = await api.submitTurn(selectedBot.name, message);
        const id = data.run_id || data.id || data.run?.id;
        if (!id) throw new Error("The server did not return a run ID.");
        setActiveRun({ id: String(id) });
        setPhase("running");
        setRunDetail("Kiro is working in this bot's persistent session.");
      } catch (error) {
        const message2 = (error as Error).message;
        setParts((current) => [...current, { type: "error", text: message2 }]);
        finishRun("error", message2);
        showToast(message2 || "Could not start run", true);
      }
    },
    [selectedBot, activeRun, surface.kind, finishRun, showToast],
  );

  const cancelRun = useCallback(async () => {
    if (!activeRun) return;
    setPhase("stopping");
    setRunDetail("Requesting a clean stop…");
    try {
      await api.cancelRun(activeRun.id);
    } catch (error) {
      setPhase("running");
      setRunDetail("");
      showToast((error as Error).message || "Could not cancel run", true);
    }
  }, [activeRun, showToast]);

  const decidePermission = useCallback(
    async (id: string, decision: "once" | "reject") => {
      const permission = permissions.find((item) => item.id === id);
      try {
        if (permission?.runId && permission.requestId && permission.id.length === 32) {
          await api.decideInteraction(permission.id, decision);
        } else if (activeRun) {
          await api.decidePermission(activeRun.id, permission?.requestId || id, decision);
        } else {
          throw new Error("This approval is no longer attached to an active run.");
        }
        setPermissions((current) => current.filter((permission) => permission.id !== id));
        setParts((current) => current.filter((part) => !(part.type === "approval" && part.id === id)));
        setPhase("running");
        setRunDetail("Approval recorded. Continuing the run.");
      } catch (error) {
        showToast((error as Error).message || "Could not submit decision", true);
      }
    },
    [activeRun, permissions, showToast],
  );

  // ---- Management actions ----------------------------------------------

  const guard = useCallback(
    async (action: () => Promise<unknown>, success?: string) => {
      try {
        await action();
        if (success) showToast(success);
        await loadManagement();
      } catch (error) {
        showToast((error as Error).message, true);
      }
    },
    [loadManagement, showToast],
  );

  const workActions: WorkActions = useMemo(
    () => ({
      onNewRoutine: () => setDialog("routine"),
      onToggleRoutine: (routine: Routine) => void guard(() => api.patchRoutine(routine.id, { enabled: !routine.enabled })),
      onDeleteRoutine: (routine: Routine) => void guard(() => api.deleteRoutine(routine.id)),
      onNewCoding: () => setDialog("coding"),
      onApproveCoding: (execution: CodingExecution) =>
        void guard(() => api.approveCodingExecution(execution.id, execution.version), "Verified handoff approved."),
      onCancelCoding: (execution: CodingExecution) => void guard(() => api.cancelCodingExecution(execution.id)),
      onNewDelegation: () => setWorkspace("workflows"),
      onStartDelegation: (plan: DelegationPlan) => void guard(() => api.startDelegation(plan.id)),
      onCancelDelegation: (plan: DelegationPlan) => void guard(() => api.cancelDelegation(plan.id)),
      onNewChannel: () => setDialog("channel"),
      onCopyWebhook: (channel: Channel) => {
        const path = `/hooks/${channel.kind}/${encodeURIComponent(channel.id)}`;
        navigator.clipboard
          .writeText(`${location.origin}${path}`)
          .then(() => showToast("Webhook URL copied."))
          .catch(() => showToast("Could not copy the URL.", true));
      },
      onToggleChannel: (channel: Channel) => void guard(() => api.patchChannel(channel.id, { enabled: !channel.enabled })),
      onDeleteChannel: (channel: Channel) => void guard(() => api.deleteChannel(channel.id)),
    }),
    [guard, showToast],
  );

  const safetyActions: SafetyActions = useMemo(
    () => ({
      onSavePolicy: async (policy: Policy) => {
        if (!selectedBot) return;
        await guard(() => api.savePolicy(selectedBot.name, policy), "Safety policy saved.");
      },
      onNewPlugin: () => setDialog("plugin"),
      onDisconnectPlugin: (pluginId: string) => {
        if (!selectedBot) return;
        void guard(() => api.unbindPlugin(selectedBot.name, pluginId));
      },
    }),
    [guard, selectedBot],
  );

  useEffect(() => {
    if ((inspectTab !== "work" && workspace !== "workflows") || !selectedBot) return;
    const timer = window.setInterval(() => {
      void api.delegations().then((plans) => setManagement((c) => ({ ...c, delegations: plans as DelegationPlan[] }))).catch(() => undefined);
      void api.codingExecutions().then((executions) => setManagement((c) => ({ ...c, codingExecutions: executions as CodingExecution[] }))).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [inspectTab, selectedBot, workspace]);

  const changeTab = useCallback(
    (tab: InspectTab) => {
      setInspectTab(tab);
      setInspectPinned(true);
      if (tab !== "run") void loadManagement();
    },
    [loadManagement],
  );

  // ---- Derived -----------------------------------------------------------

  const busy = phase === "starting" || phase === "running" || phase === "waiting" || phase === "stopping";
  const inspectOpen = Boolean(inspectPinned || busy || permissions.length > 0);
  const localLive = phase === "running" || phase === "waiting" || phase === "starting";

  const channelLabel = useMemo(() => {
    if (surface.kind !== "channel") return "";
    const channel = channels.find((item) => item.id === surface.id);
    return channel?.kind === "telegram" ? "Telegram" : channel?.name || "Remote";
  }, [surface, channels]);

  const threadParts = useMemo<Part[]>(
    () => (surface.kind === "channel" ? channelToParts(surface, channelEvents, channelLabel) : parts),
    [surface, channelEvents, channelLabel, parts],
  );

  const composerDisabled =
    !selectedBot || surface.kind === "channel" || phase === "running" || phase === "waiting" || phase === "starting";

  const closeDialog = useCallback(() => setDialog(null), []);
  const doneAndReload = useCallback(() => {
    void loadManagement();
    void loadBots();
  }, [loadManagement, loadBots]);

  const dialogProps = { open: dialog !== null, onClose: closeDialog, bot: selectedBot, bots, onDone: doneAndReload };

  return (
    <div className="app">
      <Sidebar
        bots={bots}
        selectedBot={selectedBot?.name ?? null}
        onSelectBot={selectBotByName}
        channels={channels}
        channelEvents={channelEvents}
        surface={surface}
        onSelectSurface={selectSurface}
        unread={unread}
        localLive={localLive}
        connected={connected}
        open={sidebarOpen}
        theme={theme}
        onToggleTheme={toggleTheme}
        onNewBot={() => setDialog("bot")}
        workspace={workspace}
        onWorkspaceChange={setWorkspace}
      />

      <main className="main">
        <header className="header">
          <div className="header-brand">
            <button
              type="button"
              className="hamburger"
              aria-label="Toggle sidebar"
              onClick={() => setSidebarOpen((open) => !open)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
              </svg>
            </button>
            <button
              type="button"
              className="header-logo"
              aria-label="Back to landing page"
              onClick={onExit}
            >
              <KiroGlyph size={20} />
            </button>
            <span style={{ fontWeight: 600, fontSize: "0.95rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {workspace === "workflows" ? "Workflow playground" : selectedBot ? selectedBot.name : "Choose a bot"}
            </span>
          </div>
          <div className="header-actions">
            <button
              type="button"
              className="workflow-launch"
              onClick={() => setWorkspace("workflows")}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
                <rect x="3" y="4" width="6" height="5" rx="1" />
                <rect x="15" y="15" width="6" height="5" rx="1" />
                <path d="M9 6.5h3a4 4 0 0 1 4 4V15M9 6.5l2-2m-2 2 2 2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Workflows
            </button>
            <span className="status-pill" data-state={phase}>
              <span className="status-dot" aria-hidden />
              {PHASE_TITLE[phase]}
            </span>
            <button
              type="button"
              className={`icon-btn${inspectOpen ? " active" : ""}`}
              aria-pressed={inspectOpen}
              onClick={() => setInspectPinned(!inspectPinned)}
            >
              Inspect
            </button>
          </div>
        </header>

        {workspace === "workflows" ? (
          <WorkflowPlayground
            bots={bots}
            plans={management.delegations}
            onRefresh={doneAndReload}
            onStart={(plan) => void guard(() => api.startDelegation(plan.id), "Workflow started.")}
            onCancel={(plan) => void guard(() => api.cancelDelegation(plan.id), "Workflow cancelled.")}
            onBackToChat={() => setWorkspace("conversation")}
          />
        ) : <>
        <div ref={containerRef} className="thread-scroll" onScroll={onScroll}>
          <Thread
            parts={threadParts}
            emptyGreeting={
              surface.kind === "channel"
                ? `Waiting on ${channelLabel || "this channel"}`
                : selectedBot
                  ? `What should ${selectedBot.name} do?`
                  : "Create a bot to begin"
            }
            suggestions={SUGGESTIONS}
            onSuggestion={(text) => void submitTurn(text)}
            onApproval={(id, decision) => void decidePermission(id, decision)}
          />
        </div>

        {!stuck && threadParts.length > 0 && (
          <button type="button" className="jump-latest" onClick={() => scrollToLatest()}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
              <path d="M12 5v14M19 12l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
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
              : selectedBot?.model || selectedBot?.agent || selectedBot?.cwd || "Select a bot to begin"
          }
          mirrorNote={surface.kind === "channel"}
          placeholder={selectedBot ? "Message bot…" : "Select a bot to begin"}
          onSubmit={(message) => void submitTurn(message)}
          onStop={() => void cancelRun()}
        />
        </>}
      </main>

      <InspectPanel
        open={inspectOpen}
        tab={inspectTab}
        onTab={changeTab}
        onClose={() => setInspectPinned(false)}
        inspectTitle={selectedBot?.name ? `Activity · ${selectedBot.name}` : "Activity"}
        phase={phase}
        runDetail={runDetail}
        permissions={permissions}
        onDecide={(id, decision) => void decidePermission(id, decision)}
        timeline={timeline}
        management={management}
        workActions={workActions}
        safetyActions={safetyActions}
        hasBot={Boolean(selectedBot)}
      />

      {dialog === "bot" && <CreateBotDialog {...dialogProps} />}
      {dialog === "routine" && <RoutineDialog {...dialogProps} />}
      {dialog === "plugin" && <PluginDialog {...dialogProps} />}
      {dialog === "channel" && <ChannelDialog {...dialogProps} />}
      {dialog === "coding" && <CodingDialog {...dialogProps} />}

      {activeRun && <RunStream key={activeRun.id} run={activeRun} onEvent={handleStreamEvent} />}
    </div>
  );
}

type View = "landing" | "engineering" | "console";

function resolveView(): View {
  if (isMarketingDeploy) {
    if (location.hash.includes("engineering")) return "engineering";
    return "landing";
  }
  if (new URLSearchParams(location.search).has("bot")) return "console";
  if (location.hash.includes("console")) return "console";
  if (location.hash.includes("engineering")) return "engineering";
  return "landing";
}

export function App() {
  const [view, setView] = useState<View>(resolveView);

  useEffect(() => {
    const onHashChange = () => setView(resolveView());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    const scroller = document.querySelector(".ed") as HTMLElement | null;
    scroller?.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [view]);

  const enterConsole = useCallback(() => {
    if (isMarketingDeploy) {
      history.replaceState(null, "", "#start-local");
      setView("landing");
      requestAnimationFrame(() => {
        document.getElementById("start-local")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      return;
    }
    history.replaceState(null, "", "#console");
    setView("console");
  }, []);

  const openEngineering = useCallback(() => {
    history.replaceState(null, "", "#engineering");
    setView("engineering");
  }, []);

  const exitToLanding = useCallback(() => {
    history.replaceState(null, "", location.pathname);
    setView("landing");
  }, []);

  return (
    <ToastProvider>
      {view === "console" ? (
        <ControlRoom onExit={exitToLanding} />
      ) : view === "engineering" ? (
        <EngineeringPage onEnterConsole={enterConsole} onBackToLanding={exitToLanding} />
      ) : (
        <LandingPage onEnterConsole={enterConsole} onOpenEngineering={openEngineering} />
      )}
    </ToastProvider>
  );
}

export default App;
