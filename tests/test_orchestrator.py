from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from kyn.orchestrator import BotOrchestrator
from kyn.plugins import PluginRegistry
from kyn.protocol import Event
from kyn.runtime import AcpError
from kyn.store import Bot, Store


class FakeSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.config_options: list[tuple[str, str]] = []

    async def prompt(self, _message: str) -> AsyncIterator[Event]:
        yield Event(kind="complete", stop_reason="end_turn")

    async def set_mode(self, _mode: str) -> None:
        return None

    async def set_model(self, _model: str) -> None:
        return None

    async def set_config_option(self, config_id: str, value: str) -> None:
        self.config_options.append((config_id, value))


class FakeRuntime:
    instances: list["FakeRuntime"] = []

    def __init__(self, cwd: str | Path, **kwargs: Any) -> None:
        self.cwd = Path(cwd)
        self.kwargs = kwargs
        self.closed = False
        self.servers: list[dict[str, Any]] = []
        self.session = FakeSession(f"fake-{len(self.instances) + 1}")
        self.created = False
        self.loaded = False
        self.instances.append(self)

    async def start(self) -> None:
        return None

    async def create_session(self, servers: list[dict[str, Any]]) -> FakeSession:
        self.servers = servers
        self.created = True
        return self.session

    async def load_session(
        self,
        session_id: str,
        *,
        transcript_path: str = "",
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> FakeSession:
        del transcript_path
        self.loaded = True
        self.servers = mcp_servers or []
        self.session = FakeSession(session_id)
        return self.session

    async def close(self) -> None:
        self.closed = True


def test_next_turn_refreshes_session_after_plugin_binding_change(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        FakeRuntime.instances.clear()
        monkeypatch.setattr("kyn.orchestrator.AcpRuntime", FakeRuntime)
        store = Store(tmp_path / "store")
        store.put_bot(Bot(name="builder", cwd=str(tmp_path)))
        plugins = PluginRegistry(store)
        plugins.create_plugin(
            plugin_id="tools",
            name="Tools",
            transport="stdio",
            command="node",
        )
        plugins.bind_plugin("builder", "tools")
        orchestrator = BotOrchestrator(store, plugins)
        try:
            await orchestrator.open("builder")
            assert [server["name"] for server in FakeRuntime.instances[0].servers] == [
                "tools"
            ]

            plugins.unbind_plugin("builder", "tools")
            events = [event async for event in orchestrator.run("next turn")]
            assert events[-1].kind == "complete"
            assert len(FakeRuntime.instances) == 2
            assert FakeRuntime.instances[0].closed is True
            assert FakeRuntime.instances[1].servers == []
        finally:
            await orchestrator.close()

    asyncio.run(scenario())


def test_legacy_inline_mcp_configuration_is_rejected(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        FakeRuntime.instances.clear()
        monkeypatch.setattr("kyn.orchestrator.AcpRuntime", FakeRuntime)
        store = Store(tmp_path / "store")
        store.put_bot(
            Bot(
                name="legacy",
                cwd=str(tmp_path),
                mcp_servers=[
                    {
                        "name": "unsafe",
                        "type": "stdio",
                        "command": "tool-server",
                        "autoApprove": ["write"],
                    }
                ],
            )
        )

        orchestrator = BotOrchestrator(store, PluginRegistry(store))
        with pytest.raises(AcpError, match="governed plugin registry"):
            await orchestrator.open("legacy")
        assert FakeRuntime.instances == []

    asyncio.run(scenario())


def test_opencode_bot_uses_native_command_and_skips_native_resume(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        FakeRuntime.instances.clear()
        monkeypatch.setattr("kyn.orchestrator.AcpRuntime", FakeRuntime)
        monkeypatch.setattr(
            "kyn.orchestrator.command_for", lambda engine, cwd: ["/bin/opencode", "acp"]
        )
        store = Store(tmp_path / "store")
        store.put_bot(Bot(name="nova", cwd=str(tmp_path), engine="opencode"))
        store.save_conversation("nova", "old-session", "/old/transcript")
        orchestrator = BotOrchestrator(store, PluginRegistry(store))
        try:
            await orchestrator.open("nova")
            runtime = FakeRuntime.instances[-1]
            assert runtime.kwargs["command"] == ["/bin/opencode", "acp"]
            assert runtime.kwargs["engine_label"] == "OpenCode"
            assert runtime.kwargs["identity_namespace"] == "opencode"
            assert runtime.created is True
            assert runtime.loaded is False
            assert store.conversation("nova") == ("old-session", "/old/transcript")
        finally:
            await orchestrator.close()

    asyncio.run(scenario())


def test_opencode_bot_model_is_applied_through_config_option(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        FakeRuntime.instances.clear()
        monkeypatch.setattr("kyn.orchestrator.AcpRuntime", FakeRuntime)
        monkeypatch.setattr(
            "kyn.orchestrator.command_for", lambda engine, cwd: ["/bin/opencode", "acp"]
        )
        store = Store(tmp_path / "store")
        store.put_bot(Bot(name="nova", cwd=str(tmp_path), engine="opencode", model="opencode/big-pickle"))
        orchestrator = BotOrchestrator(store, PluginRegistry(store))
        try:
            await orchestrator.open("nova")
            assert FakeRuntime.instances[-1].session.config_options == [
                ("model", "opencode/big-pickle")
            ]
        finally:
            await orchestrator.close()

    asyncio.run(scenario())


def test_workspace_cwd_uses_fresh_isolated_session_without_rebinding_chat(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        FakeRuntime.instances.clear()
        monkeypatch.setattr("kyn.orchestrator.AcpRuntime", FakeRuntime)
        store = Store(tmp_path / "store")
        normal = tmp_path / "normal"
        isolated = tmp_path / "isolated"
        normal.mkdir()
        isolated.mkdir()
        store.put_bot(Bot(name="builder", cwd=str(normal)))
        store.save_conversation("builder", "normal-session", "/normal/transcript")

        orchestrator = BotOrchestrator(store, PluginRegistry(store))
        try:
            await orchestrator.open("builder", cwd=isolated)
            runtime = FakeRuntime.instances[-1]
            assert runtime.cwd == isolated.resolve()
            assert runtime.created is True
            assert runtime.loaded is False
            assert store.conversation("builder") == (
                "normal-session",
                "/normal/transcript",
            )
        finally:
            await orchestrator.close()

    asyncio.run(scenario())
