export interface Bot {
  name: string;
  cwd?: string;
  engine?: string;
  model?: string;
  agent?: string;
  effort?: string;
  brief?: string;
}

export interface PluginPlaceTemplate {
  id: string;
  name: string;
  blurb: string;
  docs_url: string;
  transport: string;
  installed: boolean;
  missing_secrets: string[];
  warning?: string;
  config_schema: {
    key: string;
    label: string;
    required: boolean;
    secret: boolean;
    placeholder?: string;
    hint?: string;
  }[];
}

export interface PluginSecrets {
  plugin_id: string;
  secrets: string[];
}

export interface StoredEvent {
  sequence?: number;
  kind?: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface HistoryTurn {
  id?: number;
  prompt?: string;
  message?: string;
  input?: string;
  events?: StoredEvent[];
  activity?: StoredEvent[];
}

export type SurfaceKind = "local" | "channel";

export interface Surface {
  kind: SurfaceKind;
  id?: string;
  threadKey?: string;
}

export interface Group {
  id: string;
  name: string;
  aim: string;
  members: string[];
  max_rounds: number;
  /** "sequential" (take turns) or "parallel" (everyone replies at once). */
  reply_mode: string;
  status: string;
  error?: string;
  created_at?: string;
  updated_at?: string;
  /** Bot slated to speak next (mention routing); present on detail payloads. */
  speaker?: string | null;
  speaker_reason?: string;
  /** Present on list responses. */
  running?: boolean;
  message_count?: number;
}

export type GroupRole = "human" | "bot" | "system";

export interface GroupMessage {
  id: number;
  group_id: string;
  author: string;
  role: GroupRole;
  text: string;
  round?: number;
  run_id?: string;
  created_at?: string;
}

export interface GroupDetail {
  group: Group;
  members: Bot[];
  messages: GroupMessage[];
  running: boolean;
  speaking: { bot?: string; run_id?: string; bots?: { bot: string; run_id?: string }[] };
  /** Pinned handoff brief every member sees above the transcript. */
  context_note?: string;
}

export type RunPhase = "idle" | "starting" | "running" | "waiting" | "stopping" | "error";

export interface RunState {
  phase: RunPhase;
  detail: string;
}

export interface PermissionRequest {
  id: string;
  title: string;
  runId?: string;
  requestId?: string;
  toolName?: string;
  source?: string;
}

export interface Interaction {
  id: string;
  run_id: string;
  bot_name: string;
  actor: string;
  kind: "permission";
  request_id: string;
  title: string;
  tool_name: string;
  status: "pending" | "resolved" | "expired";
  decision: string;
  decided_by: string;
  created_at: string;
  resolved_at: string;
  /** Permit-line position for pending asks: 0 holds the permit (answer first). */
  queue_position?: number | null;
}

export interface RunSummary {
  id: string;
  bot_name: string;
  message: string;
  actor?: string;
  engine?: string;
  status: string;
  error?: string;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface RunDetail extends RunSummary {
  stop_reason?: string;
  events?: {
    sequence?: number;
    kind?: string;
    text?: string;
    title?: string;
    tool_name?: string;
    stop_reason?: string;
  }[];
}

export interface TimelineEntry {
  id: number;
  kind: "tool" | "permission" | "error" | "complete" | "info";
  detail: string;
  at: string;
}

export interface Policy {
  approval_mode?: string;
  allowed_tools?: string[];
  denied_tools?: string[];
  max_turns_per_hour?: number;
  max_concurrent_runs?: number;
  max_daily_runs?: number;
  auto_failover?: boolean;
  failover_engines?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface Routine {
  id: string;
  name: string;
  trigger_kind: string;
  interval_seconds?: number;
  run_at?: string;
  next_run_at?: string;
  enabled: boolean;
}

export interface Plugin {
  id: string;
  name: string;
  transport?: string;
}

export interface BotPluginBinding {
  plugin_id: string;
  allow_tools?: string[];
  enabled?: boolean;
}

export interface AuditItem {
  event_type: string;
  outcome: string;
  reason?: string;
  canonical_tool_name?: string;
  created_at: string;
}

export interface DelegationPlan {
  id: string;
  name: string;
  status: string;
  max_fanout?: number;
  max_depth?: number;
  created_at?: string;
  updated_at?: string;
}

export interface DelegationNode {
  id: string;
  bot_name: string;
  prompt: string;
  status: string;
  depth?: number;
  ordinal?: number;
  result?: unknown;
  error?: string;
}

export interface DelegationEdge {
  source: string;
  target: string;
}

export interface DelegationDetail {
  plan: DelegationPlan;
  nodes: DelegationNode[];
  edges: DelegationEdge[];
  aggregation?: { counts?: Record<string, number>; nodes?: DelegationNode[] };
}

export interface CodingExecution {
  id: string;
  status: string;
  version?: number;
  error?: string;
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
  spec?: {
    task?: string;
    builder_bot?: string;
    reviewer_bot?: string;
    repo_path?: string;
    checks?: { name: string; argv: string[] }[];
    max_repairs?: number;
  };
  result?: { repair_attempts_used?: number };
}

export interface Task {
  id: string;
  status: string;
  task_status: "open" | "merged" | "abandoned";
  version?: number;
  builder_bot?: string;
  reviewer_bot?: string;
  repo_path?: string;
  branch?: string;
  base?: string;
  task?: string;
  error?: string;
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
  worktree_path?: string | null;
  files?: { path: string; status: string }[];
  checks?: { name: string; status: "pending" | "passed" | "failed" | "timeout" | "unknown"; duration_seconds?: number }[];
  review?: { approved?: boolean; summary?: string; findings?: string[]; blocking_findings?: string[] } | null;
}

export interface TaskDiff {
  id: string;
  branch?: string;
  base?: string;
  files: { path: string; status: string }[];
  diff: string;
  truncated: boolean;
}

export interface Channel {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
  bot_name?: string;
  outbound_delivery_configured?: boolean;
}

export interface ChannelEvent {
  id: string;
  binding_id: string;
  thread_key?: string;
  text?: string;
  response_text?: string;
  error?: string;
  status: string;
  sender?: string;
  source?: string;
  created_at?: string;
  run_id?: string;
}

export interface MemoryRecord {
  request_text?: string;
  response_text?: string;
  scope?: string;
  created_at?: string;
}

export interface MemoryFact {
  id: string;
  bot_name: string;
  fact: string;
  entities: string[];
  source: string;
  actor: string;
  pinned: boolean;
  valid_from: string;
  invalid_at: string | null;
  superseded_by: string | null;
  created_at: string;
}

export type LiveMessage =
  | { type: "hello" }
  | { type: "ping" }
  | { type: "channel_event"; channel?: { id?: string; kind?: string }; event: ChannelEvent }
  /** Roster push: a bot or group was created/updated/deleted — re-read that scope now. */
  | { type: "roster"; scope: "bots" | "groups"; action: "created" | "updated" | "deleted"; name: string };

export type StreamEnvelope = {
  type?: string;
  kind?: string;
  id?: number;
  sequence?: number;
  offset?: number;
  event?: Record<string, unknown>;
  data?: Record<string, unknown>;
  run?: { status?: string; stop_reason?: string; error?: string };
  detail?: string;
  title?: string;
  text?: string;
  content?: string;
  message?: string;
  stop_reason?: string;
  request_id?: string;
  requestId?: string;
  interaction_id?: string;
};
