from __future__ import annotations

import sys

from .plugins import Plugin, PluginRegistry
from .store import Store


CONTROL_PLUGIN_ID = "kiro-control"
CONTROL_TOOLS = (
    "list_bots",
    "list_team_plans",
    "get_team_plan",
    "create_team_plan",
    "start_team_plan",
    "cancel_team_plan",
    "call_bot",
)


def ensure_internal_control(store: Store, plugins: PluginRegistry) -> None:
    """Install the reserved host-control MCP and bind it to every named bot."""

    desired = Plugin(
        id=CONTROL_PLUGIN_ID,
        name="KYN Control",
        transport="stdio",
        command=sys.executable,
        args=("-m", "kyn.control_mcp"),
        enabled=True,
    )
    current = plugins.get_plugin(CONTROL_PLUGIN_ID)
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
            CONTROL_PLUGIN_ID,
            name=desired.name,
            transport=desired.transport,
            command=desired.command,
            args=desired.args,
            env={},
            enabled=True,
        )
    for bot in store.list_bots():
        ensure_bot_control(plugins, bot.name)


def ensure_bot_control(plugins: PluginRegistry, bot_name: str) -> None:
    binding = plugins.get_binding(bot_name, CONTROL_PLUGIN_ID)
    if (
        binding is not None
        and binding.enabled
        and binding.allow_tools == CONTROL_TOOLS
        and not binding.deny_tools
    ):
        return
    plugins.bind_plugin(
        bot_name,
        CONTROL_PLUGIN_ID,
        allow_tools=CONTROL_TOOLS,
        deny_tools=(),
        auto_approve_tools=(),
        timeout_ms=600_000,
    )
