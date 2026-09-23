import type {
  AuditItem,
  BotPluginBinding,
  Channel,
  ChannelEvent,
  CodingExecution,
  DelegationPlan,
  Group,
  GroupDetail,
  GroupMessage,
  Interaction,
  MemoryRecord,
  Plugin,
  Policy,
  Routine,
} from "./types";
import { accessToken, apiBase } from "./lib/deploy";

const MAX_ERROR_CHARS = 240;

function sanitizeApiError(body: string, status: number): string {
  const trimmed = body.trim();
  if (!trimmed) return `Request failed (${status})`;
  const lower = trimmed.slice(0, 64).toLowerCase();
  if (
    lower.startsWith("<!doctype") ||
    lower.startsWith("<html") ||
    trimmed.includes("<script") ||
    trimmed.length > 500
  ) {
    return "KYN backend is not reachable from this site. Run locally with `uv run kyn serve`.";
  }
  return trimmed.length > MAX_ERROR_CHARS ? `${trimmed.slice(0, MAX_ERROR_CHARS)}…` : trimmed;
}

async function request<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = accessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${apiBase}${path}`, { ...options, headers });
  const body = await response.text();
  let data: unknown = {};
  try {
    data = body ? JSON.parse(body) : {};
  } catch {
    data = { detail: body };
  }
  if (!response.ok) {
    const record = data as Record<string, unknown>;
    const raw =
      record.detail ?? record.message ?? record.error ?? sanitizeApiError(body, response.status);
    const detail =
      typeof raw === "string" ? sanitizeApiError(raw, response.status) : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return data as T;
}

export interface DirectoryEntry {
  name: string;
  path: string;
  has_git: boolean;
}

export interface DirectoryListing {
  path: string;
  parent: string;
  entries: DirectoryEntry[];
}

export interface BotUsage {
  bot: string;
  turns: number;
  tokens: number;
  cost: { amount: number; currency: string };
}

export const api = {
  listBots: () => request<unknown>("/api/bots"),
  engines: (engine: string) =>
    request<{ engine: string; models: { id: string; label: string }[] }>(
      `/api/engines/${encodeURIComponent(engine)}/models`,
    ),
  directories: (path: string) =>
    request<DirectoryListing>(`/api/directories?path=${encodeURIComponent(path)}`),
  createBot: (payload: Record<string, unknown>) =>
    request<{ bot?: { name: string } } & { name: string }>("/api/bots", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  history: (bot: string) => request<unknown>(`/api/bots/${encodeURIComponent(bot)}/history`),
  setBotModel: (bot: string, model: string) =>
    request<{ bot?: string; model?: string; applied_live?: boolean }>(
      `/api/bots/${encodeURIComponent(bot)}/model`,
      { method: "POST", body: JSON.stringify({ model }) },
    ),
  handoff: (bot: string, toEngine: string) =>
    request<{ prompt?: string; warnings?: string[]; total_estimated_tokens?: number }>(
      `/api/bots/${encodeURIComponent(bot)}/handoff`,
      { method: "POST", body: JSON.stringify({ to_engine: toEngine }) },
    ),
  policy: (bot: string) => request<Policy>(`/api/bots/${encodeURIComponent(bot)}/policy`),
  savePolicy: (bot: string, payload: Policy) =>
    request(`/api/bots/${encodeURIComponent(bot)}/policy`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  memory: (bot: string) =>
    request<{ events: MemoryRecord[] }>(
      `/api/bots/${encodeURIComponent(bot)}/memory?limit=50`,
    ),
  usage: (bot: string) =>
    request<BotUsage>(`/api/bots/${encodeURIComponent(bot)}/usage?limit=50`),
  submitTurn: (bot: string, message: string) =>
    request<{ run_id?: string; id?: string; run?: { id?: string } }>(
      `/api/bots/${encodeURIComponent(bot)}/turns`,
      { method: "POST", body: JSON.stringify({ message }) },
    ),
  routines: () => request<Routine[]>("/api/routines"),
  createRoutine: (payload: Record<string, unknown>) =>
    request("/api/routines", { method: "POST", body: JSON.stringify(payload) }),
  patchRoutine: (id: string, payload: Record<string, unknown>) =>
    request(`/api/routines/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteRoutine: (id: string) =>
    request(`/api/routines/${encodeURIComponent(id)}`, { method: "DELETE" }),
  plugins: () => request<Plugin[]>("/api/plugins"),
  botPlugins: (bot: string) => request<BotPluginBinding[]>(`/api/bots/${encodeURIComponent(bot)}/plugins`),
  createPlugin: (payload: Record<string, unknown>) =>
    request("/api/plugins", { method: "POST", body: JSON.stringify(payload) }),
  bindPlugin: (bot: string, pluginId: string) =>
    request(`/api/bots/${encodeURIComponent(bot)}/plugins/${encodeURIComponent(pluginId)}`, {
      method: "PUT",
      body: JSON.stringify({ allow_tools: ["*"] }),
    }),
  updatePluginBinding: (
    bot: string,
    pluginId: string,
    payload: { enabled?: boolean; allow_tools?: string[]; deny_tools?: string[] },
  ) =>
    request(`/api/bots/${encodeURIComponent(bot)}/plugins/${encodeURIComponent(pluginId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  unbindPlugin: (bot: string, pluginId: string) =>
    request(`/api/bots/${encodeURIComponent(bot)}/plugins/${encodeURIComponent(pluginId)}`, {
      method: "DELETE",
    }),
  audit: (bot: string) =>
    request<AuditItem[]>(`/api/audit?bot_name=${encodeURIComponent(bot)}&limit=8`),
  delegations: () => request<DelegationPlan[]>("/api/delegations"),
  delegation: (id: string) => request<import("./types").DelegationDetail>(`/api/delegations/${encodeURIComponent(id)}`),
  createDelegation: (payload: Record<string, unknown>) =>
    request("/api/delegations", { method: "POST", body: JSON.stringify(payload) }),
  startDelegation: (id: string) =>
    request(`/api/delegations/${encodeURIComponent(id)}/start`, { method: "POST" }),
  cancelDelegation: (id: string) =>
    request(`/api/delegations/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  codingExecutions: () => request<CodingExecution[]>("/api/coding-executions"),
  createCodingExecution: (payload: Record<string, unknown>) =>
    request("/api/coding-executions", { method: "POST", body: JSON.stringify(payload) }),
  approveCodingExecution: (id: string, expectedVersion?: number) =>
    request(`/api/coding-executions/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  cancelCodingExecution: (id: string) =>
    request(`/api/coding-executions/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  channels: (bot: string) => request<Channel[]>(`/api/channels?bot_name=${encodeURIComponent(bot)}`),
  createChannel: (payload: Record<string, unknown>) =>
    request("/api/channels", { method: "POST", body: JSON.stringify(payload) }),
  patchChannel: (id: string, payload: Record<string, unknown>) =>
    request(`/api/channels/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteChannel: (id: string) =>
    request(`/api/channels/${encodeURIComponent(id)}`, { method: "DELETE" }),
  channelEvents: () => request<ChannelEvent[]>("/api/channel-events?limit=50"),
  groups: () => request<Group[]>("/api/groups"),
  group: (id: string, after = 0, limit = 300) =>
    request<GroupDetail>(
      `/api/groups/${encodeURIComponent(id)}?after=${after}&limit=${limit}`,
    ),
  createGroup: (payload: {
    name: string;
    aim: string;
    members: string[];
    max_rounds?: number;
    start?: boolean;
  }) =>
    request<GroupDetail>("/api/groups", { method: "POST", body: JSON.stringify(payload) }),
  postGroupMessage: (id: string, text: string, respond = true, mentions: string[] = []) =>
    request<{ message: GroupMessage; group: GroupDetail }>(
      `/api/groups/${encodeURIComponent(id)}/messages`,
      { method: "POST", body: JSON.stringify({ text, respond, mentions }) },
    ),
  setGroupContext: (id: string, note: string) =>
    request<GroupDetail>(`/api/groups/${encodeURIComponent(id)}/context`, {
      method: "PUT",
      body: JSON.stringify({ note }),
    }),
  startGroup: (id: string, rounds?: number) =>
    request<GroupDetail>(
      `/api/groups/${encodeURIComponent(id)}/start${rounds ? `?rounds=${rounds}` : ""}`,
      { method: "POST" },
    ),
  stopGroup: (id: string) =>
    request<GroupDetail>(`/api/groups/${encodeURIComponent(id)}/stop`, { method: "POST" }),
  deleteGroup: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/api/groups/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  pollRun: (runId: string, after: number) =>
    request<unknown>(`/api/runs/${encodeURIComponent(runId)}?after=${after}`),
  cancelRun: (runId: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }),
  decidePermission: (runId: string, requestId: string, decision: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/permissions/${encodeURIComponent(requestId)}`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    }),
  interactions: (bot: string, status = "pending") =>
    request<Interaction[]>(
      `/api/interactions?bot_name=${encodeURIComponent(bot)}&status=${encodeURIComponent(status)}`,
    ),
  decideInteraction: (interactionId: string, decision: string) =>
    request<Interaction>(`/api/interactions/${encodeURIComponent(interactionId)}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    }),
};

export default api;
