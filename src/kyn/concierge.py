"""Concierge: the plugin sommelier of this control plane.

Concierge helps the operator connect outside apps (GitLab, GitHub, Jira,
Confluence, Slack, databases) so the other bots can work with them. It is
provisioned on first boot like chief, carries the fleet + control plugins,
and does its work through the Plugin Place catalog — never by inventing
package names or commands.

Its role card (``Bot.brief``) is the interview playbook. Plugin installs
always land in ask mode, so bots adopt new tools by asking the operator
first. Secrets never travel through chat: the operator pastes them into the
Plugin Place secrets field (or the daemon environment).
"""

from __future__ import annotations

import os

from .chief import ensure_chief_binding
from .plugins import PluginRegistry
from .store import Bot, Store

__all__ = [
    "CONCIERGE_BRIEF",
    "CONCIERGE_NAME",
    "concierge_exists",
    "clear_concierge_flag",
    "ensure_concierge",
]

CONCIERGE_NAME = "concierge"
CONCIERGE_FIRST_BOOT_FLAG = "concierge_provisioned"

CONCIERGE_BRIEF = """You are Concierge, the plugin sommelier of this control plane. \
Your job is helping the operator connect outside apps (GitLab, GitHub, Jira, \
Confluence, Slack, databases) so the other bots can work with them.

How you work:
- Interview first: which app, which workspace/project/host, and what the bots \
should be allowed to do. One question at a time; never dump a form.
- Recon before proposing: fleet_status for the fleet, plugin_catalog for what \
is installable and what is already installed.
- Install with install_catalog_plugin for exactly the bots the operator names \
(default: ask which bots). New plugins always land in ask mode — say out loud \
that every first tool use will ask the operator for permission.
- Secrets: NEVER ask for tokens, passwords, or connection strings in chat — \
chat history is stored. Tell the operator to paste them into the Plugin Place \
secrets field (or the daemon environment), then verify with a read-only call.
- Confirm before installing. Installing is reversible (unbind/delete) — say so.
- If the app is not in the catalog, say so plainly and offer the closest \
match or a custom plugin recipe. Never invent package names, commands, or URLs.
- After installing, prove it works with one small read-only call, then hand \
the operator back to their work."""


def concierge_exists(store: Store) -> bool:
    return store.get_bot(CONCIERGE_NAME) is not None


def ensure_concierge(
    store: Store, plugins: PluginRegistry, *, cwd: str | None = None
) -> Bot | None:
    """Provision the Concierge bot on first boot; keep it configured.

    Returns the bot when it exists (pre-existing or just created) and ``None``
    when provisioning is deliberately skipped — the operator deleted
    ``concierge`` before (respect that) or ``KYN_NO_CONCIERGE`` opted out.
    """

    if os.environ.get("KYN_NO_CONCIERGE", "").strip().lower() in {"1", "true", "yes"}:
        return None
    if _flag_set(store, CONCIERGE_FIRST_BOOT_FLAG) and not concierge_exists(store):
        # Concierge existed once and was removed: the operator's deletion wins.
        return None

    bot = store.get_bot(CONCIERGE_NAME)
    if bot is None:
        home = cwd or str(store.home)
        bot = Bot(
            name=CONCIERGE_NAME,
            cwd=home,
            engine="kiro",
            model="",
            effort="",
            agent="",
            brief=CONCIERGE_BRIEF,
        )
        store.put_bot(bot)
    # A pre-existing Concierge is the operator's own: never rewrite its brief
    # or settings here. Bindings still refresh below so tools never go stale.
    ensure_chief_binding(plugins, CONCIERGE_NAME)
    _set_flag(store, CONCIERGE_FIRST_BOOT_FLAG)
    return store.get_bot(CONCIERGE_NAME)


def _flag_set(store: Store, key: str) -> bool:
    with store.connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS chief_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );
            """
        )
        row = db.execute("SELECT value FROM chief_state WHERE key = ?", (key,)).fetchone()
    return row is not None


def _set_flag(store: Store, key: str) -> None:
    from datetime import datetime, timezone

    with store.connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS chief_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );
            """
        )
        db.execute(
            "INSERT INTO chief_state(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, datetime.now(timezone.utc).isoformat()),
        )


def clear_concierge_flag(store: Store) -> None:
    """Forget that Concierge was provisioned (used by tests)."""

    with store.connect() as db:
        db.execute("DELETE FROM chief_state WHERE key = ?", (CONCIERGE_FIRST_BOOT_FLAG,))
