# Ari positioning

This is the source of truth for product language. Describe what the current app
does and make its boundaries easy to find.

## One-line position

Ari is a shared workspace for Kiro, OpenCode, and Codex agents, with one place to
route work, connect tools, follow progress, and review what comes back.

## Core promise

Give each bot a clear role and the right engine. Carry work between agents with
useful context, gather approvals and tasks in one work inbox, and keep important
actions reviewable.

## Who it is for

- Developers who use more than one coding-agent engine.
- Builders who want projects, bots, and ongoing work in one control room.
- People who route issues and requests from chat or external channels to agents.
- Developers who want isolated coding tasks, real checks, a second review, and
  an explicit handoff before merging.
- People who want to choose which MCP tools each bot can use.

## Message pillars

### One workspace for several engines

Create named bots backed by Kiro, OpenCode, or Codex. Each engine keeps its own
model access, account, and native tool execution. Ari provides the shared
workspace around those engines.

### Move work forward with context

Hand off from one bot to another, including a bounded conversation summary and
repository evidence. Create focused cross-bot calls or compose a durable team
workflow with visible dependencies and outputs.

### Keep the queue legible

The Work inbox gathers pending approvals, tasks, runs, workflows, and incoming
channel events. The Tasks view shows branch state, checks, reviewer findings,
changed files, and the diff before merge or abandon.

### Connect tools deliberately

Browse the plugin catalogue, register MCP servers, and bind them to selected
bots. Secrets are referenced through environment variables. Tool approvals
follow the bot's configured policy.

### Make progress reviewable

Coding tasks use an isolated worktree and branch, run user-provided checks,
allow bounded repair, and request an independent bot review. A person approves
the handoff before Ari merges reviewed work into the selected base branch. Ari
does not open pull requests or publish changes.

## Current capabilities

- Kiro, OpenCode, and Codex ACP engines, selected per bot.
- Cross-engine handoff with a portable brief, recent history, and repository
  evidence.
- Per-bot conversations, policies, model settings, MCP connections, and memory.
- A Work inbox for approvals, coding tasks, runs, workflows, and channel events.
- Reviewable Git tasks with checks, bounded repair, an independent reviewer,
  diff review, merge, and abandon actions.
- Durable schedules, multi-bot workflows, and focused bot calls.
- Plugin catalogue for MCP integrations and per-bot bindings.
- Slack, GitHub, WhatsApp Cloud API, Telegram, normalized email webhooks, and
  signed generic webhooks.
- A responsive browser control room and macOS app with local data storage.

## Honest boundaries

- The macOS app runs the Ari service on that Mac. It must stay online for
  scheduled work and incoming channel events. Another device can connect over a
  private Tailscale network.
- Remote hosting is supported as a deployment option. The operator configures
  its bearer token, origin policy, network exposure, and engine installations.
- There are no built-in user accounts, SSO, organization tenancy, or team
  administration.
- Engine credentials and model availability come from the selected engine;
  Ari does not supply provider accounts.
- Coding tasks can merge reviewed work into a local base branch after approval.
  Ari does not create pull requests or publish releases.
- Email is a normalized signed webhook contract, not native Gmail sync.
- Telegram uses polling from the Ari service; the other listed channel adapters
  use provider webhooks.
- Bots can make focused calls and follow durable workflow plans. They do not
  have free-form asynchronous mailboxes.

## Voice

- Lead with the outcome and show the workflow that gets there.
- Use “engine” for Kiro, OpenCode, or Codex and “bot” for an Ari identity.
- Explain which service owns model access and sign-in.
- Say where a person reviews or approves work.
- Avoid claims of enterprise readiness, unattended publishing, or work that
  continues after a local host is offline.

## Primary calls to action

1. Open Ari.
2. Explore the workspace.
3. See how Ari works.
4. Start with one bot and one real task.
