from __future__ import annotations

from pathlib import Path

from kyn.control_mcp import _dispatch, _validated_base_url
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
