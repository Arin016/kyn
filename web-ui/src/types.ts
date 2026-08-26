export interface Bot {
  name: string;
  cwd?: string;
  model?: string;
  agent?: string;
  effort?: string;
}

export interface StoredEvent {
  sequence?: number;
  kind?: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface HistoryTurn {
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
}

export interface CodingExecution {
  id: string;
  status: string;
  version?: number;
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

export interface Channel {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
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

export type LiveMessage =
  | { type: "hello" }
  | { type: "ping" }
  | { type: "channel_event"; channel?: { id?: string; kind?: string }; event: ChannelEvent };

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
