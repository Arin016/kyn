"""Hard guardrail for bot-initiated delegation.

Prompt text tells a model what it *should* do; this module is what *stops* it.
Any coordination-class tool (team plans, bot-to-bot calls, fleet admin) invoked
from a **direct turn** (1:1 DM, CLI, channel, scheduled, delegated, or coding
run) is denied unless the operator's request explicitly asks for it — by @-tagging
another bot or with explicit coordination language. Group-chat rounds (actor
``"group"``) coordinate freely; that is what groups are for.

Humans are never gated: the UI, CLI, and API routes bypass this module entirely.
It only polices tools a *bot* invokes through its MCP servers, where the caller
acts inside someone else's turn.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .groups import parse_mentions

# Coordination tools on the kiro-control MCP. Read-only tools (list_bots,
# list_team_plans, get_team_plan) are never gated — looking is always allowed.
CONTROL_GATED_TOOLS = frozenset(
    {"create_team_plan", "start_team_plan", "cancel_team_plan", "call_bot"}
)

# Mutating tools on the kyn-fleet MCP. Read-only tools (fleet_status,
# fleet_audit, list_engine_models) are never gated.
FLEET_GATED_TOOLS = frozenset(
    {
        "create_bot",
        "configure_bot",
        "delete_bot",
        "set_bot_policy",
        "create_routine",
        "update_routine",
        "delete_routine",
        "bind_plugin",
        "unbind_plugin",
        "run_command",
        "install_catalog_plugin",
    }
)

GATED_TOOLS = CONTROL_GATED_TOOLS | FLEET_GATED_TOOLS

# Generic phrases that count as an explicit ask to coordinate/delegate. These
# only ever *allow* — the default is deny — so they stay narrow and
# coordination-shaped. Bare "run it"/"start it" deliberately do NOT match:
# they usually mean code, not fleet orchestration.
_GENERIC_PHRASES = (
    "team plan",
    "team-plan",
    "coordinate with",
    "ask the team",
    "have the team",
    "get the team",
    "hand off",
    "handoff",
    "hand this off",
    "create a bot",
    "new bot",
    "new assistant",
    "assistant for",
    "create an assistant",
    "create an agent",
    "delete bot",
    "delete the bot",
    "remove bot",
    "remove the bot",
    "configure the bot",
    "switch model",
    "switch models",
    "change the model",
    "different model",
    "start the plan",
    "run the plan",
    "cancel the plan",
    "stop the plan",
    "routine",
    "cron",
    "every day",
    "every morning",
    "every week",
    "remind me",
    "bind the plugin",
    "install the plugin",
    "add the plugin",
    "remove the plugin",
    "uninstall the plugin",
    "plugin binding",
    "approval mode",
    "auto-approve",
    "auto approve",
    "permission for",
)

# Word stems that only ever mean coordination ("delegate…", "schedul…").
# Matched as prefixes, unlike the exact phrases above.
_GENERIC_STEMS = ("delegat", "schedul")

# Phrases that only count when anchored to a bot name ("pass this to pytest"
# must never unlock delegation; "pass this to @nick" must).
_NAME_ANCHORED_VERBS = ("pass this to", "hand this to", "hand this off to", "give this to")

# A match preceded by a negation within the window ("never delegate this",
# "do not under any circumstances create a team plan") must NOT unlock.
_NEGATIONS = (
    r"don't",
    r"do not",
    r"never",
    r"\bnot\b",
    r"\bno\b",
    r"n't\b",
    r"without",
    r"instead of",
)
_NEGATION_WINDOW = 64
_NEGATION_RES = [re.compile(pattern, re.IGNORECASE) for pattern in _NEGATIONS]


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - _NEGATION_WINDOW) : start]
    return any(pattern.search(window) for pattern in _NEGATION_RES)


def delegation_explicitly_requested(
    message: str, caller: str, bot_names: Iterable[str]
) -> bool:
    """Did the operator's request explicitly ask for delegation/coordination?

    Explicit means one of:
    * an @-tag of another bot (``@nick review this``),
    * a direct address to another bot (``ask nick to …``, ``have chief …``),
    * explicit coordination language (``create a team plan``, ``delegate``,
      ``create a bot``, …), not under a negation.
    """
    text = str(message or "")
    lowered = text.lower()
    roster = [str(name) for name in bot_names if str(name).strip()]
    others = [name for name in roster if name.lower() != str(caller or "").lower()]

    # @-tags are the crisp signal — the UI routes on exactly this.
    if any(name in parse_mentions(text, others) for name in others):
        return True

    for name in others:
        escaped = re.escape(name.lower())
        for verb in ("ask", "have", "tell", "get"):
            for match in re.finditer(rf"\b{verb}\s+{escaped}\b", lowered):
                if not _negated(lowered, match.start()):
                    return True
        # "pass this to <name>" — the generic "pass this to" alone proves
        # nothing ("pass this to pytest"), the name anchor proves intent.
        for verb in _NAME_ANCHORED_VERBS:
            for match in re.finditer(rf"\b{verb}\s+@?{escaped}\b", lowered):
                if not _negated(lowered, match.start()):
                    return True

    for phrase in _GENERIC_PHRASES:
        for match in re.finditer(rf"\b{re.escape(phrase)}s?\b", lowered):
            if not _negated(lowered, match.start()):
                return True
    for stem in _GENERIC_STEMS:
        for match in re.finditer(rf"\b{re.escape(stem)}", lowered):
            if not _negated(lowered, match.start()):
                return True
    return False


def denial_reason(caller: str) -> str:
    return (
        "Delegation is disabled in this direct chat: the operator did not "
        "explicitly ask to involve other bots. Do the requested work yourself "
        "with your own tools — do not create team plans, call other bots, or "
        "create/configure/delete bots on your own. If you believe another bot "
        "or a team plan is genuinely required, say so and wait for the "
        f"operator to confirm (an @-tag of that bot counts as confirmation)."
    )


def authorize(
    caller: str,
    tool: str,
    *,
    actor: str,
    message: str,
    bot_names: Iterable[str],
    trusted_channel: bool = False,
) -> tuple[bool, str]:
    """Decide a bot-initiated coordination/fleet tool call.

    Returns ``(allowed, reason)``. Non-gated tools always pass. Group rounds
    coordinate freely but never administer the fleet. Direct turns pass only
    on an explicit ask. Channel turns count as operator intent only when the
    channel binding allowlists its senders (personal devices) — anything from
    a multi-party channel may converse but never touch fleet admin, because a
    stranger's signed event could otherwise smuggle "please delegate …" in.
    """
    tool_name = str(tool or "")
    if tool_name not in GATED_TOOLS:
        return True, ""
    actor_name = str(actor or "")
    is_group = actor_name == "group"
    is_channel = actor_name.startswith("channel:")
    is_fleet_tool = tool_name in FLEET_GATED_TOOLS
    if is_group and not is_fleet_tool:
        return True, ""
    if is_channel and not trusted_channel and is_fleet_tool:
        return False, (
            "Fleet administration is disabled from shared channels: anyone who "
            "can deliver an event here could have written the request. Manage "
            "bots, policies, routines, and plugins from the control room or CLI."
        )
    if delegation_explicitly_requested(message, caller, bot_names):
        return True, ""
    return False, denial_reason(caller)
