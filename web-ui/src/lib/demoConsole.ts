import type { Part } from "../components/chat/Message";
import type { ManagementData } from "../components/inspect/InspectPanel";
import type {
  Bot,
  Channel,
  ChannelEvent,
  DelegationDetail,
  GroupDetail,
} from "../types";

export const DEMO_ASSISTANT_REPLY =
  "KYN is the local control plane for durable Kiro agents — sessions, channels, approvals, and verified coding handoffs around `kiro-cli acp`.\n\nFrom your message I'd start with the riskiest open work: deployment hardening, channel UX, and workspace lease recovery. Run locally with `uv run kyn serve` to wire this to your real bots.";

export const DEMO_TELEGRAM_IN = "Hey — anything blocked on the launch checklist?";
export const DEMO_TELEGRAM_OUT =
  "Nothing blocking. Checklist is green; I'll watch the deploy thread and ping you if approvals queue up.";

export const DEMO_BOTS: Bot[] = [
  { name: "chief", cwd: "~/.kyn", model: "Kiro" },
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
      type: "reasoning",
      id: "demo-reasoning-1",
      text:
        "The ask has two halves: what this repo is, and which open TODOs carry the most risk. I'll read the README, look at the daemon entry point, then grep for TODO markers and rank them by blast radius.",
      running: false,
    },
    {
      type: "tool",
      id: "demo-tool-1",
      title: "filesystem.read · README.md",
      status: "done",
      detail: "Read 214 lines from README.md (install, daemon, channels, workflows).",
    },
    {
      type: "tool",
      id: "demo-tool-2",
      title: "search.grep · TODO|FIXME",
      status: "done",
      detail: "src/kyn/server.py:412  TODO: harden remote deploy auth\nsrc/kyn/channels.py:88  TODO: group mention routing\nsrc/kyn/workspaces.py:301  FIXME: lease recovery on restart",
    },
    {
      type: "tool",
      id: "demo-tool-3",
      title: "shell.exec · uv run pytest -q",
      status: "done",
      detail: "192 passed, 1 warning in 44.42s",
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
      approval_mode: "allow_list",
      allowed_tools: ["filesystem.read", "search.grep", "shell.exec"],
      denied_tools: ["git.push"],
      max_turns_per_hour: 40,
      max_concurrent_runs: 3,
      max_daily_runs: 200,
      auto_failover: true,
      failover_engines: ["opencode"],
    },
    routines: [
      {
        id: "demo-routine-1",
        name: "Morning digest",
        trigger_kind: "interval",
        interval_seconds: 3600,
        enabled: true,
        next_run_at: new Date(Date.now() + 11 * 60 * 1000).toISOString(),
      },
      {
        id: "demo-routine-2",
        name: "Dependency sweep",
        trigger_kind: "interval",
        interval_seconds: 86_400,
        enabled: false,
        next_run_at: new Date(Date.now() + 5 * 3600 * 1000).toISOString(),
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
    delegations: [
      DEMO_DELEGATION_DETAIL.plan,
      {
        id: "demo-plan-triage",
        name: "Triage the open bug queue",
        status: "running",
        max_fanout: 3,
        max_depth: 2,
        created_at: new Date(Date.now() - 9 * 60 * 1000).toISOString(),
      },
    ],
    codingExecutions: [
      {
        id: "demo-coding-1",
        status: "awaiting_handoff",
        version: 3,
        spec: {
          task: "Fix the workspace lease recovery path and add a regression test.",
          builder_bot: "builder",
          reviewer_bot: "reviewer",
          repo_path: "~/personal/kyn",
          checks: [
            { name: "tests", argv: ["pytest", "-q"] },
            { name: "lint", argv: ["ruff", "check", "."] },
          ],
          max_repairs: 1,
        },
        result: { repair_attempts_used: 1 },
      },
      {
        id: "demo-coding-2",
        status: "ready",
        version: 5,
        spec: {
          task: "Harden the remote guard against replayed signatures.",
          builder_bot: "triage",
          reviewer_bot: "reviewer",
          checks: [{ name: "tests", argv: ["pytest", "-q"] }],
        },
        result: { repair_attempts_used: 0 },
      },
    ],
    channels: [
      DEMO_CHANNEL,
      { id: "demo-github", name: "Kyn repo events", kind: "github", enabled: false, outbound_delivery_configured: true },
    ],
    channelEvents: [
      ...DEMO_CHANNEL_EVENTS,
      {
        id: "demo-ch-2",
        binding_id: "demo-github",
        thread_key: "issue-412",
        text: "New comment on issue #412: the lease retry budget is undocumented.",
        status: "failed",
        sender: "arin16tumbagi",
        source: "github",
        error: "Reviewer bot was busy; request was not retried",
        created_at: new Date(Date.now() - 26 * 60 * 1000).toISOString(),
      },
    ],
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
  return `Demo reply from ${message.trim().slice(0, 48)}${message.length > 48 ? "…" : ""}: KYN keeps persistent native-engine sessions, routes work through policies, and streams live activity here. Install locally to run the real agent.`;
}

export function demoDelegationDetail(planId: string): DelegationDetail | null {
  if (planId === DEMO_DELEGATION_PLAN_ID) return DEMO_DELEGATION_DETAIL;
  return null;
}

export const DEMO_GROUP_DETAIL: GroupDetail = {
  group: {
    id: "demo-group-launch",
    name: "Launch room",
    aim: "Ship the 0.4 release notes with one verified changelog entry per merged pull request.",
    members: ["builder", "reviewer", "triage"],
    max_rounds: 3,
    status: "done",
    running: false,
    message_count: 6,
  },
  members: DEMO_BOTS,
  running: false,
  speaking: {},
  messages: [
    {
      id: 1,
      group_id: "demo-group-launch",
      author: "builder",
      role: "bot",
      text: "I'll draft the notes section by section. Starting with the durability changes: queued runs now survive a daemon restart, and workspace leases renew on a heartbeat.",
      created_at: "2026-08-26T12:10:00Z",
    },
    {
      id: 2,
      group_id: "demo-group-launch",
      author: "reviewer",
      role: "bot",
      text: "Reviewed the diff for the lease heartbeat. Two gaps: the expiry path is untested, and the retry budget isn't surfaced in the console. I'll add the missing test if we agree on the budget default.",
      created_at: "2026-08-26T12:11:30Z",
    },
    {
      id: 3,
      group_id: "demo-group-launch",
      author: "triage",
      role: "bot",
      text: "Tracked both as release blockers. I'll fold them into the changelog entry under “known limits” so the notes stay honest about what shipped.",
      created_at: "2026-08-26T12:12:40Z",
    },
    {
      id: 4,
      group_id: "demo-group-launch",
      author: "You",
      role: "human",
      text: "Keep the notes under 300 words and link the PR numbers.",
      created_at: "2026-08-26T12:13:10Z",
    },
    {
      id: 5,
      group_id: "demo-group-launch",
      author: "builder",
      role: "bot",
      text: "Trimmed to 280 words and linked each entry to its PR. The reliability section now cites #412 and #418, and the “known limits” entry cites #420.",
      created_at: "2026-08-26T12:15:00Z",
    },
    {
      id: 6,
      group_id: "demo-group-launch",
      author: "kyn",
      role: "system",
      text: "triage marked the shared aim as met. Pause here or keep going.",
      created_at: "2026-08-26T12:15:20Z",
    },
  ],
};

export function demoGroupReply(message: string, author: string): string {
  return `${author} here — noted: “${message.trim().slice(0, 60)}${message.length > 60 ? "…" : ""}”. I'll fold that into the shared aim and hand the next step to the room. Run \`uv run kyn serve\` to see real bots take turns.`;
}
