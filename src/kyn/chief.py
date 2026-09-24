"""Reserved fleet-control plugin and the chief-of-staff bootstrap.

Two things live here:

* The **fleet plugin** — a second reserved MCP (:mod:`kyn.fleet_mcp`) with
  admin-grade tools (create/configure/delete bots, policies, routines,
  bindings, host commands). It is *not* bound to every bot: only bots that
  opt in carry it, because it can reconfigure the whole daemon.

* :func:`ensure_chief_of_staff` — idempotently provisions a default chief
  bot on first boot (skipped silently when the operator deleted it or the
  deployment opted out), binds it the coordination and fleet plugins, and
  re-binds every other chief-designated bot. Any bot can be promoted to a
  chief by binding the fleet plugin to it; ``chief`` is simply the one that
  exists out of the box.
"""

from __future__ import annotations

import sys

from .internal_control import CONTROL_PLUGIN_ID, ensure_bot_control, ensure_control_plugin
from .plugins import Plugin, PluginRegistry
from .store import Bot, Store

__all__ = [
    "CHIEF_NAME",
    "FLEET_PLUGIN_ID",
    "FLEET_TOOLS",
    "chief_exists",
    "clear_chief_flag",
    "ensure_chief_binding",
    "ensure_chief_of_staff",
    "ensure_fleet_plugin",
]

FLEET_PLUGIN_ID = "kyn-fleet"
FLEET_TOOLS = (
    "fleet_status",
    "create_bot",
    "configure_bot",
    "delete_bot",
    "set_bot_policy",
    "create_routine",
    "update_routine",
    "delete_routine",
    "bind_plugin",
    "unbind_plugin",
    "list_engine_models",
    "run_command",
    "fleet_audit",
    "plugin_catalog",
    "install_catalog_plugin",
)

CHIEF_NAME = "chief"
CHIEF_FIRST_BOOT_FLAG = "chief_provisioned"


def ensure_fleet_plugin(plugins: PluginRegistry) -> None:
    """Install the reserved fleet MCP (not bound to any bot by default)."""

    desired = Plugin(
        id=FLEET_PLUGIN_ID,
        name="KYN Fleet Control",
        transport="stdio",
        command=sys.executable,
        args=("-m", "kyn.fleet_mcp"),
        enabled=True,
    )
    current = plugins.get_plugin(FLEET_PLUGIN_ID)
    if current is None:
        plugins.create_plugin(desired)
    elif (
        current.name != desired.name
        or current.transport != desired.transport
        or current.command != desired.command
        or current.args != desired.args
        or current.env
        or not current.enabled
    ):
        plugins.update_plugin(
            FLEET_PLUGIN_ID,
            name=desired.name,
            transport=desired.transport,
            command=desired.command,
            args=desired.args,
            env={},
            enabled=True,
        )


def ensure_chief_binding(plugins: PluginRegistry, bot_name: str) -> None:
    """Bind coordination + fleet tools to a chief-designated bot."""

    # Both reserved plugins must exist before bindings can reference them.
    ensure_control_plugin(plugins)
    if plugins.get_plugin(FLEET_PLUGIN_ID) is None:
        ensure_fleet_plugin(plugins)
    ensure_bot_control(plugins, bot_name)
    plugins.bind_plugin(
        bot_name,
        FLEET_PLUGIN_ID,
        allow_tools=FLEET_TOOLS,
        deny_tools=(),
        auto_approve_tools=(),
        timeout_ms=600_000,
    )


def chief_exists(store: Store) -> bool:
    return store.get_bot(CHIEF_NAME) is not None


def ensure_chief_of_staff(store: Store, plugins: PluginRegistry, *, cwd: str | None = None) -> Bot | None:
    """Provision the default chief bot on first boot; keep it configured.

    Returns the chief bot when it exists (pre-existing or just created) and
    ``None`` when provisioning is deliberately skipped — either because the
    operator deleted ``chief`` before (respect that) or because the
    ``KYN_NO_CHIEF`` environment flag opted this machine out.
    """

    import os

    # The chief binds the coordination MCP too, so make sure the reserved
    # control plugin exists even when this runs without server startup.
    ensure_control_plugin(plugins)
    ensure_fleet_plugin(plugins)
    if os.environ.get("KYN_NO_CHIEF", "").strip().lower() in {"1", "true", "yes"}:
        return None
    if _flag_set(store, CHIEF_FIRST_BOOT_FLAG) and not chief_exists(store):
        # Chief existed once and was removed: the operator's deletion wins.
        return None

    bot = store.get_bot(CHIEF_NAME)
    if bot is None:
        home = cwd or str(store.home)
        bot = Bot(
            name=CHIEF_NAME,
            cwd=home,
            engine="kiro",
            model="",
            effort="",
            agent="",
        )
        store.put_bot(bot)
    ensure_chief_binding(plugins, CHIEF_NAME)
    _set_flag(store, CHIEF_FIRST_BOOT_FLAG)
    return store.get_bot(CHIEF_NAME)


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


def clear_chief_flag(store: Store) -> None:
    """Forget that chief was provisioned (used by tests)."""

    with store.connect() as db:
        db.execute("DELETE FROM chief_state WHERE key = ?", (CHIEF_FIRST_BOOT_FLAG,))
