from __future__ import annotations

import asyncio

import pytest

from kyn import setup


def test_setup_status_includes_installed_codex_acp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        setup,
        "_find_binary",
        lambda name: f"/test/bin/{name}" if name in {"kiro-cli", "opencode", "codex-acp"} else None,
    )

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"test version", None

    async def create_process(*args: object, **kwargs: object) -> Process:
        return Process()

    monkeypatch.setattr(setup.asyncio, "create_subprocess_exec", create_process)

    result = asyncio.run(setup.setup_status())

    codex = next(engine for engine in result["engines"] if engine["id"] == "codex")
    assert codex == {
        "id": "codex",
        "label": "Codex",
        "available": True,
        "binary": "/test/bin/codex-acp",
        "version": "test version",
    }


def test_codex_install_uses_published_packages_and_checks_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    calls: list[tuple[object, ...]] = []

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"installed", None

    async def create_process(*args: object, **kwargs: object) -> Process:
        calls.append(args)
        return Process()

    monkeypatch.setattr(setup.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(
        setup,
        "_find_binary",
        lambda name: "/Users/test/.local/bin/codex-acp" if name == "codex-acp" else None,
    )

    result = asyncio.run(setup.install_engine("codex"))

    assert result["id"] == "codex"
    assert result["binary"] == "/Users/test/.local/bin/codex-acp"
    command = str(calls[0][2])
    assert "@openai/codex" in command
    assert "@agentclientprotocol/codex-acp" in command
    assert "--prefix \"$HOME/.local\"" in command


def test_codex_install_reports_missing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup.sys, "platform", "darwin")

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"installed", None

    async def create_process(*args: object, **kwargs: object) -> Process:
        return Process()

    monkeypatch.setattr(setup.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(setup, "_find_binary", lambda _name: None)

    with pytest.raises(RuntimeError, match="codex-acp.*not on the app's PATH"):
        asyncio.run(setup.install_engine("codex"))
