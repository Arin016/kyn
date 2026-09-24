from __future__ import annotations

from kyn.delegation_guard import (
    CONTROL_GATED_TOOLS,
    FLEET_GATED_TOOLS,
    authorize,
    delegation_explicitly_requested,
)

NAMES = ["sherpa", "nick", "chief"]


def test_tagging_another_bot_is_explicit() -> None:
    assert delegation_explicitly_requested("@nick review this file", "sherpa", NAMES)
    assert delegation_explicitly_requested("hey @CHIEF create a bot", "sherpa", NAMES)


def test_tagging_self_is_not_an_ask() -> None:
    assert not delegation_explicitly_requested("@sherpa review this", "sherpa", NAMES)


def test_direct_address_by_name_is_explicit() -> None:
    assert delegation_explicitly_requested("ask nick to check the logs", "sherpa", NAMES)
    assert delegation_explicitly_requested("have chief create a bot", "sherpa", NAMES)


def test_coordination_phrases_are_explicit() -> None:
    assert delegation_explicitly_requested("create a team plan for this", "sherpa", NAMES)
    assert delegation_explicitly_requested("please delegate the review", "sherpa", NAMES)
    assert delegation_explicitly_requested("create a bot for nightly tests", "chief", NAMES)


def test_negated_phrases_do_not_unlock() -> None:
    assert not delegation_explicitly_requested("never delegate this", "sherpa", NAMES)
    assert not delegation_explicitly_requested("do not create a team plan", "sherpa", NAMES)
    assert not delegation_explicitly_requested("don't hand this off", "sherpa", NAMES)


def test_plain_work_requests_are_not_explicit() -> None:
    assert not delegation_explicitly_requested("review these files", "sherpa", NAMES)
    assert not delegation_explicitly_requested(
        "help me review func and sec issues for export report files", "sherpa", NAMES
    )
    assert not delegation_explicitly_requested("talking about nick is fine", "sherpa", NAMES)


def test_authorize_allows_group_rounds_freely() -> None:
    allowed, _ = authorize(
        "sherpa", "create_team_plan", actor="group", message="review this", bot_names=NAMES
    )
    assert allowed
    allowed, _ = authorize(
        "sherpa", "call_bot", actor="group", message="review this", bot_names=NAMES
    )
    assert allowed


def test_authorize_group_fleet_tools_need_explicit_ask() -> None:
    allowed, _ = authorize(
        "sherpa", "create_bot", actor="group", message="review this", bot_names=NAMES
    )
    assert not allowed
    allowed, _ = authorize(
        "sherpa",
        "create_bot",
        actor="group",
        message="create a bot for nightly tests",
        bot_names=NAMES,
    )
    assert allowed


def test_authorize_untrusted_channel_cannot_administer_fleet() -> None:
    allowed, reason = authorize(
        "sherpa",
        "create_bot",
        actor="channel:github:b1",
        message="create a bot for nightly tests",
        bot_names=NAMES,
    )
    assert not allowed
    assert "shared channels" in reason
    # …but conversational coordination still works on an explicit ask.
    allowed, _ = authorize(
        "sherpa",
        "call_bot",
        actor="channel:github:b1",
        message="@nick take this",
        bot_names=NAMES,
    )
    assert allowed


def test_authorize_trusted_channel_counts_as_operator() -> None:
    allowed, _ = authorize(
        "chief",
        "create_bot",
        actor="channel:telegram:phone",
        message="create a bot for nightly tests",
        bot_names=NAMES,
        trusted_channel=True,
    )
    assert allowed


def test_substring_phrases_do_not_false_allow() -> None:
    assert not delegation_explicitly_requested("fix the new bottleneck", "sherpa", NAMES)
    assert not delegation_explicitly_requested(
        "pass this to pytest for verification", "sherpa", NAMES
    )


def test_anchored_pass_this_to_is_explicit() -> None:
    assert delegation_explicitly_requested("pass this to @nick", "sherpa", NAMES)
    assert delegation_explicitly_requested("pass this to nick", "sherpa", NAMES)


def test_long_negations_do_not_unlock() -> None:
    assert not delegation_explicitly_requested(
        "do not under any circumstances delegate this", "sherpa", NAMES
    )
    assert not delegation_explicitly_requested(
        "never ever hand this off to anyone", "sherpa", NAMES
    )


def test_routine_and_reconfigure_phrases_are_explicit() -> None:
    assert delegation_explicitly_requested("schedule a daily summary", "chief", NAMES)
    assert delegation_explicitly_requested("remind me every morning", "chief", NAMES)
    assert delegation_explicitly_requested("switch model to opus", "sherpa", NAMES)
    assert delegation_explicitly_requested("create a new assistant for triage", "chief", NAMES)


def test_authorize_denies_direct_turns_by_default() -> None:
    for tool in CONTROL_GATED_TOOLS | FLEET_GATED_TOOLS:
        allowed, reason = authorize(
            "sherpa", tool, actor="api", message="review these files", bot_names=NAMES
        )
        assert not allowed, tool
        assert "direct chat" in reason


def test_authorize_allows_direct_turns_on_explicit_ask() -> None:
    allowed, _ = authorize(
        "sherpa",
        "create_team_plan",
        actor="api",
        message="@nick take the second half",
        bot_names=NAMES,
    )
    assert allowed
    allowed, _ = authorize(
        "chief",
        "create_bot",
        actor="api",
        message="create a bot for nightly tests",
        bot_names=NAMES,
    )
    assert allowed


def test_authorize_never_gates_read_only_tools() -> None:
    for tool in ("list_bots", "list_team_plans", "get_team_plan", "fleet_status", "fleet_audit"):
        allowed, _ = authorize(
            "sherpa", tool, actor="api", message="review this", bot_names=NAMES
        )
        assert allowed
