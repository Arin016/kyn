import type { Part } from "../components/chat/Message";
import type { ManagementData } from "../components/inspect/InspectPanel";
import type {
  Bot,
  Channel,
  ChannelEvent,
  DelegationDetail,
} from "../types";

export const DEMO_ASSISTANT_REPLY =
  "KYN is the local control plane for durable Kiro agents — sessions, channels, approvals, and verified coding handoffs around `kiro-cli acp`.\n\nFrom your message I'd start with the riskiest open work: deployment hardening, channel UX, and workspace lease recovery. Run locally with `uv run kyn serve` to wire this to your real bots.";

export const DEMO_TELEGRAM_IN = "Hey — anything blocked on the launch checklist?";
export const DEMO_TELEGRAM_OUT =
  "Nothing blocking. Checklist is green; I'll watch the deploy thread and ping you if approvals queue up.";

export const DEMO_BOTS: Bot[] = [
  { name: "builder", cwd: "~/personal", model: "Kiro" },
  { name: "reviewer", cwd: "~/personal", model: "Kiro" },
  { name: "triage", cwd: "~/personal/kyn", agent: "triage" },
];

export const DEMO_CHANNEL: Channel = {
  id: "demo-telegram",
  name: "Phone Telegram",
  kind: "telegram",
  enabled: true,
  outbound_delivery_configured: true,
};

export const DEMO_CHANNEL_EVENTS: ChannelEvent[] = [
  {
    id: "demo-ch-1",
    binding_id: DEMO_CHANNEL.id,
    thread_key: "8961333191",
    text: DEMO_TELEGRAM_IN,
    status: "responded",
    sender: "8961333191",
    source: "telegram",
    created_at: "2026-08-26T12:04:00Z",
    response_text: DEMO_TELEGRAM_OUT,
    run_id: "demo-run-telegram",
  },
];

export const DEMO_THREADS: Record<string, Part[]> = {
  builder: [
    {
      type: "user",
      text: "Summarize what this repo does and list the riskiest TODOs.",
    },
    {
      type: "assistant-text",
      text:
        "This is a local control plane for durable Kiro agents. It owns sessions, channels, approvals, and verified coding handoffs around `kiro-cli acp`.\n\nRiskiest TODOs:\n1. Harden remote deployment auth\n2. Expand Telegram group mention UX\n3. Document workspace lease recovery",
    },
  ],
  reviewer: [],
  triage: [],
};

export const DEMO_DELEGATION_PLAN_ID = "demo-workflow-ship";

export const DEMO_DELEGATION_DETAIL: DelegationDetail = {
  plan: {
    id: DEMO_DELEGATION_PLAN_ID,
    name: "Ship the release safely",
    status: "succeeded",
    max_fanout: 2,
    max_depth: 3,
  },
  nodes: [
    {
      id: "node-1",
      bot_name: "builder",
      prompt: "Patch the release checklist doc and run tests.",
      status: "succeeded",
      depth: 0,
      ordinal: 0,
      result: "Checklist updated; pytest green in isolated worktree.",
    },
    {
      id: "node-2",
      bot_name: "reviewer",
      prompt: "Review the builder output for scope and safety.",
      status: "succeeded",
      depth: 1,
      ordinal: 0,
      result: "No policy bypasses; ready for human handoff.",
    },
  ],
  edges: [{ source: "node-1", target: "node-2" }],
};

export function demoManagementData(): ManagementData {
  return {
    policy: {
      approval_mode: "ask",
      allowed_tools: ["filesystem.*", "bash"],
      denied_tools: [],
      max_turns_per_hour: 40,
      max_concurrent_runs: 3,
      max_daily_runs: 200,
    },
    routines: [
      {
        id: "demo-routine-1",
        name: "Morning digest",
        trigger_kind: "interval",
        interval_seconds: 86400,
        enabled: true,
        next_run_at: "2026-08-27T09:00:00Z",
      },
    ],
    plugins: [
      { id: "kiro-control", name: "KYN control", transport: "stdio" },
      { id: "filesystem", name: "Filesystem", transport: "stdio" },
    ],
    bindings: [
      { plugin_id: "kiro-control", enabled: true, allow_tools: ["*"] },
      { plugin_id: "filesystem", enabled: true, allow_tools: ["read", "write"] },
    ],
    audit: [
      {
        event_type: "permission_decision",
        outcome: "once",
        canonical_tool_name: "bash",
        created_at: "2026-08-26T11:58:00Z",
      },
      {
        event_type: "run_complete",
        outcome: "complete",
        created_at: "2026-08-26T11:57:00Z",
      },
    ],
    delegations: [DEMO_DELEGATION_DETAIL.plan],
    codingExecutions: [],
    channels: [DEMO_CHANNEL],
    channelEvents: DEMO_CHANNEL_EVENTS,
    memoryRecords: [
      {
        request_text: "Summarize what this repo does and list the riskiest TODOs.",
        response_text: "Local control plane for durable Kiro agents with governed handoffs.",
        scope: "local:builder",
        created_at: "2026-08-26T11:55:00Z",
      },
    ],
  };
}

export function demoResponseFor(message: string): string {
  const lower = message.toLowerCase();
  if (lower.includes("todo")) return DEMO_ASSISTANT_REPLY;
  if (lower.includes("summarize") || lower.includes("summary")) {
    return "KYN wraps `kiro-cli acp` with durable bots, governed tool approval, channels, schedules, and team workflows. This preview mirrors the real console — connect a local daemon to run against your repos.";
  }
  return `Demo reply from ${message.trim().slice(0, 48)}${message.length > 48 ? "…" : ""}: KYN keeps persistent Kiro sessions, routes work through policies, and streams live activity here. Install locally to run the real agent.`;
}

export function demoDelegationDetail(planId: string): DelegationDetail | null {
  if (planId === DEMO_DELEGATION_PLAN_ID) return DEMO_DELEGATION_DETAIL;
  return null;
}
