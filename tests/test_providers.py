from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kyn.providers import (
    ProviderError,
    command_for,
    initialize_params,
    models_for,
    normalize_engine,
    spec,
)
from kyn.store import Bot, Store


def test_normalize_engine_defaults_to_kiro() -> None:
    assert normalize_engine(None) == "kiro"
    assert normalize_engine(" OpenCode ") == "opencode"
    with pytest.raises(ProviderError):
        normalize_engine("cursor")


def test_opencode_command_uses_native_binary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("kyn.providers.shutil.which", lambda name: "/usr/local/bin/opencode" if name == "opencode" else None)
    command = command_for("opencode", str(tmp_path))
    assert command == ["/usr/local/bin/opencode", "acp", "--cwd", str(tmp_path)]


def test_opencode_command_requires_binary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("kyn.providers.shutil.which", lambda name: None)
    with pytest.raises(ProviderError, match="opencode is not installed"):
        command_for("opencode", str(tmp_path))


def test_codex_command_prefers_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KYN_CODEX_ACP", "/opt/codex-acp")
    monkeypatch.setattr("kyn.providers.shutil.which", lambda name: None)
    assert command_for("codex", str(tmp_path)) == ["/opt/codex-acp"]


def test_models_for_lists_opencode_models(monkeypatch) -> None:
    class Completed:
        returncode = 0
        stdout = b"opencode/big-pickle\nanthropic/claude-x\nnot-a-model\n"

    monkeypatch.setattr("kyn.providers.shutil.which", lambda name: "/bin/opencode")
    monkeypatch.setattr("kyn.providers.subprocess.run", lambda *args, **kwargs: Completed())
    assert models_for("opencode") == [
        {"id": "opencode/big-pickle", "label": "opencode/big-pickle"},
        {"id": "anthropic/claude-x", "label": "anthropic/claude-x"},
    ]


def test_models_for_rejects_other_engines() -> None:
    # Kiro and Codex now return curated model lists; unknown engines are rejected.
    with pytest.raises(ProviderError, match="unknown agent engine"):
        models_for("doesnotexist")


def test_models_for_curated_catalogues() -> None:
    kiro = models_for("kiro")
    assert any(item["id"] == "claude-sonnet-4-5" for item in kiro)
    codex = models_for("codex")
    assert any("codex" in item["id"] for item in codex)


def test_initialize_params_match_each_engine() -> None:
    kiro = initialize_params("kiro")
    assert kiro["protocolVersion"] == "2025-08-22"
    opencode = initialize_params("opencode")
    assert opencode["protocolVersion"] == 1
    assert opencode["clientInfo"]["name"] == "kyn"


def test_existing_bot_databases_gain_engine_column(tmp_path: Path) -> None:
    home = tmp_path / "legacy"
    home.mkdir()
    db_path = home / "kyn.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE bots (
                name TEXT PRIMARY KEY,
                cwd TEXT NOT NULL,
                agent TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                effort TEXT NOT NULL DEFAULT '',
                mcp_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO bots(name, cwd, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("legacy", str(tmp_path), "now", "now"),
        )
        connection.commit()
    finally:
        connection.close()
    store = Store(home)
    bot = store.get_bot("legacy")
    assert bot is not None
    assert bot.engine == "kiro"
    store.put_bot(Bot(name="nova", cwd=str(tmp_path), engine="opencode"))
    assert store.get_bot("nova") is not None
    assert store.get_bot("nova").engine == "opencode"
    assert spec("opencode").resume_native_conversation is False
