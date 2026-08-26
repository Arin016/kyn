# Architecture and protocol trace

## The key discovery

Kiro exposes an agent process through `kiro-cli acp`. An orchestrator does not
need to emulate Kiro or drive its terminal UI. It launches that command and
speaks ACP as newline-delimited JSON-RPC 2.0 over stdin/stdout.

The minimum connection flow is:

```text
spawn kiro-cli acp
  -> initialize
  -> session/new OR session/load
  -> optional session/set_mode
  -> optional session/set_model
  -> session/prompt
  <- session/update notifications
  <- session/request_permission requests
  -> approval/rejection response
  <- prompt response with stopReason
```

`session/cancel` is a notification, not a request. `session/new` must include
both `cwd` and `mcpServers`, even when the server list is empty.

## Where orchestration lives

Kiro owns model calls and tool execution. Kiro Bot owns:

- bot identity and configuration;
- session-to-bot mapping and resumption;
- durable turn/event history;
- approval policy and audit records;
- queues, schedules, channels, and agent-to-agent delegation;
- runtime health, concurrency limits, and recovery.

The important distinction is process versus session. One ACP process can host
multiple logical Kiro sessions. A single stdout reader must demultiplex frames
by `sessionId`, while JSON-RPC responses are correlated by request ID. Prompts
must be serialized per session, but independent sessions may run concurrently.

## Safety rules in this kernel

1. Never auto-approve a permission request that has no owning session.
2. Always answer server-to-client permission requests; silently dropping one
   can wedge the backend waiting for a response.
3. Allow only one active prompt per logical session.
4. Treat stdout as untrusted framing: ignore non-JSON and non-object lines.
5. Keep stderr drained so the subprocess cannot block on a full pipe.
6. Persist the Kiro session ID before considering a conversation durable.
7. Drive policy from Kiro's canonical `_meta.kiro` tool identity, never the
   model-authored tool title shown to a user.
8. Resolve MCP secret references only while compiling the ephemeral
   `mcpServers` launch payload; never persist or log resolved values.
9. Make the plugin registry the sole MCP source. Inline legacy server JSON and
   backend `autoApprove`/`allow_always` grants are rejected because they evade
   later host-policy revocation.
10. Reserve quotas atomically before enqueueing a run and release the lease on
   every terminal path.
11. Keep governance audit records low-cardinality and payload-free. Prompts,
    tool arguments, environment values and raw provider frames do not belong in
    the audit schema.
12. Represent each human gate as a durable, single-decision interaction. Never
    turn a per-action approval into blanket trust for the rest of a run.
13. Bind host actuation through the reserved `kiro-control` MCP with an explicit
    tool set. It is host-managed, hidden from user MCP configuration and still
    passes through ordinary permission policy.

## Implemented product layers

- Long-running daemon and WebSocket event bus.
- Responsive browser UI with persistent bot cards, history, live activity,
  approvals and cancellation.
- Per-bot FIFO workers, cross-bot concurrency and bounded run/event retention.
- Clean runtime recovery after failure or cancellation.
- Durable interval and one-time routines with transactional claims, retry
  backoff, bounded concurrency and no catch-up storms.
- Per-bot ask/deny/allow-list policy, deny precedence, fixed UTC quotas and
  immutable action audit.
- Persistent MCP registry with per-bot bindings, environment references,
  HTTPS enforcement and fail-closed launch compilation.
- Browser management views for routines, safety limits, MCP connections and
  recent audit decisions.
- Durable run queue with atomic claims, startup recovery, expiring leases and
  at-least-once replay after a hard crash.
- Durable multi-bot DAGs with bounded fan-out/depth, exclusive ready-node
  claims, dependency failure propagation, cancellation and aggregation.
- A drag-and-drop workflow board over the DAG schema plus conversational
  `create_team_plan`, inspection, cancellation and focused `call_bot` tools.
- Durable interaction ledger with reload-safe control-room decisions and
  Telegram inline decision callbacks scoped to the originating channel run.
- Detached, token-leased Git workspaces with retained material output,
  contained artifact hashing and explicit clean-only cleanup.
- Workspace-aware ACP execution with durable run-to-worktree bindings,
  per-workspace serialization, lease heartbeats and restart restoration.
- Durable coding executions with idempotent acceptance, isolated Kiro builder
  turns, direct-argv deterministic checks, bounded repair loops, independent
  reviewer bots, reviewer-mutation detection, retained artifact manifests and
  an explicit human handoff boundary.
- Authenticated external channel bindings for Slack, GitHub, Telegram, WhatsApp
  Cloud API, normalized email and generic webhooks. Telegram inbound is
  laptop-side long polling against `api.telegram.org` only. Other providers
  verify raw-body signatures, reject stale signed requests, and use public
  webhooks. The gateway deduplicates provider delivery IDs, builds bounded
  source-thread context, runs each event in a fresh external ACP session,
  submits through the governed Engine and retains the response even when
  outbound delivery is not configured.

## Next product layers

1. Produce a reproducible binary patch bundle that represents additions,
   deletions, renames and file modes, then add a separately approved publisher
   for branch, pull-request and CI repair workflows. Merge remains human-only.
2. Add a durable phase-event ledger and phase idempotency keys so every
   external side effect can be reconciled precisely after a hard crash.
3. Add asynchronous bot-to-bot mailboxes, group threads, a native Gmail OAuth/history
   synchronizer and a persistent browser/computer-use provider.
4. Add authentication, organization controls and metered provider budgets.
5. Add pluggable eval suites, model/harness routing and longitudinal quality
   data.
