from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kyn.handoff import HandoffError, compile_handoff, estimate_tokens
from kyn.protocol import Event
from kyn.store import Bot, Store


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_handoff_compiles_grounded_redacted_bundle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "KYN Test")
    (repo / "app.py").write_text("value = 1\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-q", "-m", "initial")
    (repo / "app.py").write_text("value = 2\n")

    store = Store(tmp_path / "store")
    store.put_bot(Bot(name="builder", cwd=str(repo)))
    turn_id = store.begin_turn("builder", "Fix the value without breaking callers. API key sk-12345678901234567890?")
    store.add_event(turn_id, 1, Event(kind="text", text="value = 2"))
    store.finish_turn(turn_id, "complete", "end_turn")

    bundle = compile_handoff(store, "builder", to_engine="opencode", budget_tokens=3000)

    assert bundle["from_engine"] == "kiro"
    assert bundle["to_engine"] == "opencode"
    assert "value = 2" in bundle["prompt"]
    assert "sk-12345678901234567890" not in bundle["prompt"]
    assert bundle["total_estimated_tokens"] <= 3000
    assert bundle["workspace"]["status"]
    assert estimate_tokens("abcd") == 1


def test_handoff_rejects_unknown_engine_and_captures_staged_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "KYN Test")
    (repo / "staged.txt").write_text("staged value\n")
    _git(repo, "add", "staged.txt")

    store = Store(tmp_path / "store")
    store.put_bot(Bot(name="builder", cwd=str(repo)))
    turn_id = store.begin_turn("builder", "Continue the staged work", engine="kiro")
    store.finish_turn(turn_id, "complete")

    bundle = compile_handoff(store, "builder", to_engine=" OpenCode ")
    assert bundle["to_engine"] == "opencode"
    assert "staged value" in bundle["workspace"]["diff"]

    with pytest.raises(HandoffError, match="unknown agent engine"):
        compile_handoff(store, "builder", to_engine="unknown")
