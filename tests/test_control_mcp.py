from __future__ import annotations

from pathlib import Path

import pytest

from kyn.control_mcp import _call_tool, _caller_snapshot, _dispatch, _validated_base_url
from kyn.internal_control import CONTROL_PLUGIN_ID, ensure_internal_control
from kyn.plugins import PluginRegistry
from kyn.store import Bot, Store


def test_control_mcp_advertises_durable_host_tools() -> None:
    initialized = _dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        "http://127.0.0.1:8765",
        "builder",
    )
    assert initialized is not None
    assert initialized["result"]["serverInfo"]["name"] == "kyn-control"
    listed = _dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        "http://127.0.0.1:8765",
        "builder",
    )
    names = {item["name"] for item in listed["result"]["tools"]}  # type: ignore[index]
    assert {"create_team_plan", "call_bot", "cancel_team_plan"} <= names


def test_internal_control_is_bound_to_every_bot_with_explicit_tools(tmp_path: Path) -> None:
    store = Store(tmp_path / "state")
    store.put_bot(Bot("builder", str(tmp_path)))
    plugins = PluginRegistry(store)
    ensure_internal_control(store, plugins)
    plugin = plugins.get_plugin(CONTROL_PLUGIN_ID)
    binding = plugins.get_binding("builder", CONTROL_PLUGIN_ID)
    assert plugin is not None and plugin.enabled
    assert binding is not None and "create_team_plan" in binding.allow_tools
    _generation, servers = plugins.compile_session_configuration("builder", environ={})
    control = next(item for item in servers if item["name"] == CONTROL_PLUGIN_ID)
    assert control["args"][-2:] == ["--caller", "builder"]


def test_control_origin_must_be_loopback() -> None:
    assert _validated_base_url("http://localhost:8765") == "http://localhost:8765"
    try:
        _validated_base_url("https://example.com")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback control origin was accepted")


def test_call_bot_attaches_caller_workspace_snapshot(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    import kyn.control_mcp as control_mcp

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, capture_output=True)

    posted: dict[str, object] = {}

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        if path == "/api/control/authorize":
            return {"allowed": True, "reason": ""}
        if path == "/api/bots/nick":
            return {"name": "nick", "cwd": str(repo), "engine": "opencode"}
        if path == "/api/bots/sherpa/turns":
            posted.update(payload or {})  # type: ignore[arg-type]
            return {"run_id": "run-9"}
        if path == "/api/runs/run-9":
            return {"run_id": "run-9", "status": "complete"}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(control_mcp, "_http", fake_http)
    result = _call_tool("http://127.0.0.1:8765", "nick", "call_bot", {"bot_name": "sherpa", "message": "check this"})
    assert result["status"] == "complete"
    assert "<caller_context>" in str(posted.get("message"))
    assert str(repo) in str(posted.get("message"))
    assert "caller branch:" in str(posted.get("message"))


def test_call_bot_proceeds_without_snapshot_when_caller_unknown(monkeypatch) -> None:
    import kyn.control_mcp as control_mcp

    posted: dict[str, object] = {}

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        if path == "/api/control/authorize":
            return {"allowed": True, "reason": ""}
        if path == "/api/bots/ghost":
            raise RuntimeError("no such bot")
        if path == "/api/bots/sherpa/turns":
            posted.update(payload or {})  # type: ignore[arg-type]
            return {"run_id": "run-9"}
        return {"run_id": "run-9", "status": "complete"}

    monkeypatch.setattr(control_mcp, "_http", fake_http)
    result = _call_tool("http://127.0.0.1:8765", "ghost", "call_bot", {"bot_name": "sherpa", "message": "hi"})
    assert result["status"] == "complete"
    assert str(posted.get("message")) == "hi"


def test_call_bot_timeout_reports_callee_status(monkeypatch) -> None:
    import kyn.control_mcp as control_mcp

    calls: list[tuple[str, str]] = []

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        calls.append((method, path))
        if path == "/api/control/authorize":
            return {"allowed": True, "reason": ""}
        if path == "/api/bots/nick":
            return {"name": "nick", "cwd": "/tmp", "engine": "kiro"}
        if path.endswith("/turns"):
            return {"run_id": "run-9"}
        return {"run_id": "run-9", "status": "running"}

    monkeypatch.setattr(control_mcp, "_http", fake_http)
    try:
        _call_tool(
            "http://127.0.0.1:8765",
            "nick",
            "call_bot",
            {"bot_name": "sherpa", "message": "hi", "timeout_seconds": 1},
        )
    except TimeoutError as exc:
        assert "running" in str(exc)
    else:
        raise AssertionError("expected TimeoutError")
    # A timed-out callee must be cancelled, not left running in the background.
    assert ("POST", "/api/runs/run-9/cancel") in calls


def test_call_bot_denied_without_explicit_ask(monkeypatch) -> None:
    import kyn.control_mcp as control_mcp

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        if path == "/api/control/authorize":
            return {"allowed": False, "reason": "Delegation is disabled in this direct chat"}
        raise AssertionError(f"must not reach {method} {path}")

    monkeypatch.setattr(control_mcp, "_http", fake_http)
    with pytest.raises(RuntimeError, match="Delegation is disabled"):
        _call_tool(
            "http://127.0.0.1:8765",
            "sodms-reviewer",
            "call_bot",
            {"bot_name": "chief", "message": "take this over"},
        )


def test_create_team_plan_denied_without_explicit_ask(monkeypatch) -> None:
    import kyn.control_mcp as control_mcp

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        if path == "/api/control/authorize":
            return {"allowed": False, "reason": "Delegation is disabled in this direct chat"}
        raise AssertionError(f"must not reach {method} {path}")

    monkeypatch.setattr(control_mcp, "_http", fake_http)
    with pytest.raises(RuntimeError, match="Delegation is disabled"):
        _call_tool(
            "http://127.0.0.1:8765",
            "sodms-reviewer",
            "create_team_plan",
            {"name": "rogue", "nodes": [{"id": "n1", "bot_name": "chief", "prompt": "x"}]},
        )


def test_memory_tools_advertised_and_caller_scoped(monkeypatch) -> None:
    import kyn.control_mcp as control_mcp

    assert {"memory_remember", "memory_search", "memory_forget", "memory_pin"} <= {
        item["name"] for item in control_mcp.TOOLS
    }

    calls: list[tuple[str, str, object]] = []

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        calls.append((method, path, payload))
        if path.startswith("/api/bots/nick/memory/facts") and method == "POST":
            return {"id": "fact-1", "fact": "x"}
        if path.startswith("/api/bots/nick/memory/facts") and method == "GET":
            return {"bot": "nick", "facts": []}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(control_mcp, "_http", fake_http)
    result = control_mcp._call_tool(
        "http://127.0.0.1:8765", "nick", "memory_remember", {"fact": "Deploys on Friday"}
    )
    assert result == {"id": "fact-1", "fact": "x"}
    # Caller-bound: the tool never accepts a foreign bot name.
    assert calls[0][1] == "/api/bots/nick/memory/facts"
    assert calls[0][2] == {
        "fact": "Deploys on Friday",
        "entities": [],
        "source": "",
        "actor": "nick",
    }
    result = control_mcp._call_tool(
        "http://127.0.0.1:8765", "nick", "memory_search", {"query": "deploys"}
    )
    assert result == {"bot": "nick", "facts": []}
    assert "q=deploys" in calls[1][1]

    result = control_mcp._call_tool(
        "http://127.0.0.1:8765", "nick", "memory_forget", {"fact_id": "fact-1"}
    )
    assert calls[2][1] == "/api/bots/nick/memory/facts/fact-1/forget"
    result = control_mcp._call_tool(
        "http://127.0.0.1:8765", "nick", "memory_pin", {"fact_id": "fact-1"}
    )
    assert calls[3][1] == "/api/bots/nick/memory/facts/fact-1/pin"

    with pytest.raises(ValueError, match="fact is required"):
        control_mcp._call_tool("http://127.0.0.1:8765", "nick", "memory_remember", {})
    with pytest.raises(ValueError, match="query is required"):
        control_mcp._call_tool("http://127.0.0.1:8765", "nick", "memory_search", {})
