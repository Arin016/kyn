# Kiro Bot positioning

This document is the source of truth for product language. It keeps the public story outcome-led while preventing the marketing from outrunning the prototype.

## One-line position

Kiro Bot is the local control plane for persistent Kiro agents, recurring work, and governed coding handoffs.

## Core promise

Put Kiro to work beyond a single terminal session. Give named agents clear jobs, reach them from the surfaces where work arrives, let several move concurrently, and keep consequential decisions behind deterministic boundaries.

## Who it is for

- Developers already using Kiro CLI who want work to survive a chat session.
- Small engineering teams experimenting with named agent roles and repeatable workflows.
- Builders who prefer a local, inspectable harness over opaque autonomy.
- Teams prototyping channel-driven triage, scheduled work, or verified issue-to-handoff flows.

## Message pillars

### Persistent by design

Named agents retain a Kiro session, durable conversation history, and bounded shared memory. Accepted work can recover after a controller restart.

### Reachable where work happens

The same named agent can receive work from the browser, Slack, GitHub, WhatsApp, normalized email events, signed webhooks, or Telegram. Source threads remain isolated.

### A roster, not one overloaded chat

Builders, reviewers, operators, triage agents, and coordinators can keep different context and policies. Independent agents can run concurrently; durable plans express dependencies.

### Autonomy with a hard edge

Policies, quotas, permission routing, workspace isolation, deterministic checks, mutation detection, and human handoffs live in code outside the model.

## Proof points

- Durable per-agent FIFO workers and restart recovery.
- Cross-surface memory with immutable source records.
- One-time and repeating routines.
- Multi-agent DAG execution with cancellation and bounded concurrency.
- Signature-verified remote channels and allow lists.
- Detached Git workspaces and SHA-256 artifact manifests.
- Build → check → bounded repair → independent review → human handoff.
- Environment-reference-only plugin secrets and payload-free governance audit.

## Honest boundaries

- The current product is local-first. The host machine must remain online for remote channels and background work.
- The daemon binds to loopback and has no built-in multi-user authentication or tenancy.
- The coding lifecycle does not push, open a pull request, merge, or publish.
- Email uses a normalized webhook contract rather than a native Gmail synchronizer.
- There is no persistent browser/computer-use provider.
- Delegation is a durable dependency graph, not free-form asynchronous bot-to-bot chat.

## Voice

- Lead with the job and finished outcome.
- Explain the technical mechanism only as proof.
- Prefer short, concrete sentences.
- Use “agent” for the general concept and “bot” when referring to a named Kiro Bot identity or UI object.
- Say exactly where human approval occurs.
- Never use “24/7,” “fully autonomous,” “enterprise-ready,” “exactly once,” or “works while your laptop is closed” for the current build.

## Primary calls to action

1. Meet your first bot.
2. See what it can do.
3. Inspect the engineering.
4. Start with one real job.
