from __future__ import annotations

from pathlib import Path

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

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
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
