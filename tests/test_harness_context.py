from __future__ import annotations

from kyn.harness_context import compose_execution_prompt, render_harness_context


def test_capability_contract_distinguishes_durable_bots_from_subagents() -> None:
    rendered = render_harness_context(["reviewer", "builder", "builder"])

    assert "durable dependency DAG" in rendered
    assert "temporary subagents" in rendered
    assert "Never replace this answer" in rendered
    assert "builder, reviewer" in rendered


def test_capability_contract_states_remote_and_runtime_boundaries() -> None:
    rendered = render_harness_context()

    assert "WhatsApp" in rendered
    assert "Telegram" in rendered
    assert "host machine and KYN daemon are" in rendered
    assert "separate machines" in rendered
    assert "Never say a team plan was created" in rendered
    assert "create_team_plan" in rendered
    assert "There is no blanket \"trust this run\" path" in rendered


def test_execution_prompt_keeps_evidence_separate_from_current_request() -> None:
    rendered = compose_execution_prompt(
        "Can you orchestrate multiple bots?",
        bot_names=["alpha"],
        memory_context="<memory>Earlier decision</memory>",
    )

    assert rendered.index("<kyn_control_plane>") < rendered.index("<memory>")
    assert rendered.endswith("Current request:\nCan you orchestrate multiple bots?")
