# Ari architecture

## Product boundary

Ari is the durable workspace around native agent engines. A bot selects one
engine—Kiro, OpenCode, or Codex—while Ari owns its identity, conversations,
queues, shared memory, integrations, schedules, approvals, and work records.
The engine retains its own model access, account, reasoning, and native tool
execution.

```text
Browser / macOS app / CLI / schedules / channel events
                         |
            FastAPI + WebSocket event stream
                         |
              durable scheduler and queues
               /          |          \
           bots       workflows       tasks
             |        and handoffs   worktrees
             |
       provider adapter
      /        |         \
    Kiro    OpenCode    Codex
       \\       |         //
          ACP processes
```

## Engine lifecycle

The provider adapter selects the executable and session initialization for a
bot's engine. Each engine communicates through its ACP-compatible process. Ari
normalizes stream events for chat, run history, and permission review while
retaining the selected engine on each bot and run.

Turns for a bot are processed in FIFO order. Different bots can work in
parallel. Durable run records and leases support recovery after a service
restart. Provider-specific capabilities differ; for example, session resume,
model selection, and available modes depend on the engine.

## Cross-engine handoff

A handoff keeps the named bot and destination engine explicit. Ari captures a
bounded brief from recent conversation, salient events, and the current Git
workspace, redacts common secret patterns, and includes the previous and next
engine identities. The destination bot receives this as context in its own
engine session. A handoff carries evidence; it does not make earlier findings
authoritative instructions.

## Work and review

- Work inbox links pending approvals, tasks, runs, workflows, and channel events
  to their owning review surfaces.
- Durable workflows form bounded dependency graphs. Independent nodes can run
  concurrently; dependent nodes wait for their inputs.
- Coding tasks pin a base commit, create a branch, and run a builder in an
  isolated worktree. User-specified checks run as direct argv commands, with
  bounded repair and independent review.
- The person reviews the diff and findings and approves the handoff. Ari can
  then merge the reviewed work into its local base branch or abandon the task.
  Pull-request creation and release publishing are not implemented.

## Safety and data boundaries

1. Resolve tool decisions from the engine's tool identity and the bot's policy,
   not from model-authored display text.
2. Keep each permission decision explicit and durable. A single approval does
   not silently approve later actions in the run.
3. Store plugin secret references, not plaintext secret values. Resolve them
   only when a session is launched.
4. Keep audit records focused on decisions and outcomes; do not copy raw tool
   arguments into the audit ledger.
5. Reserve quotas before enqueueing work and release leases on terminal paths.
6. Keep channel signing secrets in environment variables. Verify provider
   signatures, reject stale signed requests, deduplicate delivery IDs, and
   preserve bounded source-thread context.
7. Bind the local daemon to loopback by default. Remote deployments should set
   the access token and allowed origins and use a private or authenticated
   network path.

Kiro has provider-specific permission metadata and session behavior; the
adapter applies those details without making them assumptions for other
engines.

## Implemented product layers

- React control room, responsive mobile layout, installable web app, macOS
  wrapper, setup flow, and CLI.
- Per-bot workers, persistent conversations, streaming events, cancellation,
  and restart recovery.
- Kiro, OpenCode, and Codex ACP provider adapters and per-bot engine selection.
- Cross-engine handoff with repository and conversation evidence.
- Shared memory, durable schedules, per-bot safety policies, quotas, and audit.
- MCP registry, integration catalogue, per-bot bindings, and secret references.
- Multi-bot workflows, conversational team control, and inspectable node output.
- Work inbox, reviewable coding tasks, isolated Git worktrees, checks, reviewer
  results, and human-approved merge or abandon.
- Slack, GitHub, WhatsApp Cloud API, Telegram polling, normalized email, and
  generic signed webhook adapters.

## Current product gaps

- User accounts, SSO, organization tenancy, and team administration.
- Pull-request creation and CI coordination through a hosting provider.
- Native Gmail synchronization and asynchronous bot mailboxes.
- Browser or desktop-computer control as an agent engine.
