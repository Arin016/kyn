from __future__ import annotations

import os
from pathlib import Path

import pytest

from kyn.chief import (
    CHIEF_NAME,
    FLEET_PLUGIN_ID,
    chief_exists,
    clear_chief_flag,
    ensure_chief_binding,
    ensure_chief_of_staff,
)
from kyn.fleet_mcp import _call_tool, _dispatch, _run_command
from kyn.internal_control import CONTROL_PLUGIN_ID
from kyn.plugins import PluginRegistry
from kyn.store import Bot, Store


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("KYN_NO_CHIEF", raising=False)


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "state")


@pytest.fixture()
def plugins(store: Store) -> PluginRegistry:
    return PluginRegistry(store)


# ---- fleet MCP -------------------------------------------------------------


def test_fleet_mcp_advertises_admin_tools() -> None:
    listed = _dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        "http://127.0.0.1:8765",
    )
    assert listed is not None
    names = {item["name"] for item in listed["result"]["tools"]}  # type: ignore[index]
    assert {
        "fleet_status",
        "create_bot",
        "configure_bot",
        "delete_bot",
        "set_bot_policy",
        "create_routine",
        "bind_plugin",
        "list_engine_models",
        "run_command",
    } <= names


def test_fleet_origin_must_be_loopback() -> None:
    from kyn.fleet_mcp import _validated_base_url

    assert _validated_base_url("http://localhost:8765") == "http://localhost:8765"
    try:
        _validated_base_url("https://example.com")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback fleet origin was accepted")


def test_fleet_configure_bot_patches_only_given_fields(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        calls.append((method, path))
        if path == "/api/bots/builder" and method == "GET":
            return {"name": "builder", "model": "old-model"}
        return {"ok": True}

    monkeypatch.setattr("kyn.fleet_mcp._http", fake_http)
    result = _call_tool(
        "http://127.0.0.1:8765",
        "configure_bot",
        {"name": "builder", "model": "new-model"},
    )
    assert result == {"ok": True}
    assert calls == [("PATCH", "/api/bots/builder")]


def test_fleet_configure_bot_with_no_fields_reads(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        calls.append((method, path))
        return {"name": "builder", "model": "m"}

    monkeypatch.setattr("kyn.fleet_mcp._http", fake_http)
    result = _call_tool("http://127.0.0.1:8765", "configure_bot", {"name": "builder"})
    assert result["name"] == "builder"
    assert calls == [("GET", "/api/bots/builder")]


def test_fleet_set_bot_policy_merges_with_current(monkeypatch) -> None:
    sent: dict[str, object] = {}

    def fake_http(base: str, method: str, path: str, payload: object = None) -> object:
        if path == "/api/bots/builder/policy":
            if method == "GET":
                return {
                    "approval_mode": "allowlist",
                    "allowed_tools": ["filesystem.read"],
                    "denied_tools": [],
                    "max_turns_per_hour": 12,
                    "max_concurrent_runs": 2,
                    "max_daily_runs": 50,
                    "auto_failover": True,
                    "failover_engines": ["opencode"],
                }
            sent.update(payload or {})  # type: ignore[arg-type]
            return {"ok": True}
        raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr("kyn.fleet_mcp._http", fake_http)
    _call_tool(
        "http://127.0.0.1:8765",
        "set_bot_policy",
        {"name": "builder", "denied_tools": ["shell.exec"]},
    )
    # Untouched fields survive the partial update.
    assert sent["approval_mode"] == "allowlist"
    assert sent["allowed_tools"] == ["filesystem.read"]
    assert sent["denied_tools"] == ["shell.exec"]
    assert sent["auto_failover"] is True
    assert sent["failover_engines"] == ["opencode"]


def test_fleet_run_command_is_arglist_only_and_bounded() -> None:
    result = _run_command({"command": ["printf", "hello %s", "world"]})
    assert result["exit_code"] == 0
    assert result["stdout"] == "hello world"

    with pytest.raises(ValueError):
        _run_command({"command": "rm -rf /"})  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _run_command({"command": ["definitely-not-a-real-binary-xyz"]})


def test_fleet_run_command_times_out() -> None:
    with pytest.raises(TimeoutError):
        _run_command({"command": ["sleep", "5"], "timeout_seconds": 1})


# ---- chief bootstrap --------------------------------------------------------


def test_first_boot_provisions_chief(store: Store, plugins: PluginRegistry) -> None:
    bot = ensure_chief_of_staff(store, plugins)
    assert bot is not None
    assert bot.name == CHIEF_NAME
    assert chief_exists(store)

    fleet = plugins.get_binding(CHIEF_NAME, FLEET_PLUGIN_ID)
    control = plugins.get_binding(CHIEF_NAME, CONTROL_PLUGIN_ID)
    assert fleet is not None and fleet.enabled
    assert control is not None
    _generation, servers = plugins.compile_session_configuration(CHIEF_NAME, environ={})
    names = {item["name"] for item in servers}
    assert {CONTROL_PLUGIN_ID, FLEET_PLUGIN_ID} <= names


def test_chief_is_not_recreated_after_operator_deletes_it(
    store: Store, plugins: PluginRegistry
) -> None:
    ensure_chief_of_staff(store, plugins)
    assert chief_exists(store)
    with store.connect() as db:
        db.execute("DELETE FROM bots WHERE name = ?", (CHIEF_NAME,))

    assert ensure_chief_of_staff(store, plugins) is None
    assert not chief_exists(store)


def test_chief_config_is_repaired_on_reboot(store: Store, plugins: PluginRegistry) -> None:
    ensure_chief_of_staff(store, plugins)
    plugins.unbind_plugin(CHIEF_NAME, FLEET_PLUGIN_ID)

    ensure_chief_of_staff(store, plugins)
    binding = plugins.get_binding(CHIEF_NAME, FLEET_PLUGIN_ID)
    assert binding is not None and binding.enabled


def test_reboot_keeps_chief_without_recreating(store: Store, plugins: PluginRegistry) -> None:
    ensure_chief_of_staff(store, plugins)
    bot = ensure_chief_of_staff(store, plugins)
    assert bot is not None
    assert chief_exists(store)


def test_env_flag_opts_machine_out(store: Store, plugins: PluginRegistry, monkeypatch) -> None:
    monkeypatch.setenv("KYN_NO_CHIEF", "1")
    assert ensure_chief_of_staff(store, plugins) is None
    assert not chief_exists(store)


def test_any_bot_can_be_promoted_to_chief(store: Store, plugins: PluginRegistry) -> None:
    store.put_bot(Bot(name="sherpa", cwd=str(Path("/tmp"))))
    ensure_chief_binding(plugins, "sherpa")
    fleet = plugins.get_binding("sherpa", FLEET_PLUGIN_ID)
    assert fleet is not None and "create_bot" in fleet.allow_tools


def test_regular_bots_do_not_get_fleet_tools(store: Store, plugins: PluginRegistry) -> None:
    ensure_chief_of_staff(store, plugins)
    store.put_bot(Bot(name="worker", cwd=str(Path("/tmp"))))
    from kyn.internal_control import ensure_bot_control

    ensure_bot_control(plugins, "worker")
    assert plugins.get_binding("worker", FLEET_PLUGIN_ID) is None


# ---- HTTP endpoints ---------------------------------------------------------


def _make_app(store: Store, plugins: PluginRegistry | None = None):
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    from kyn.server import create_app

    class NoopEngine:
        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def submit(self, bot_name: str, message: str) -> str:  # pragma: no cover
            raise AssertionError("no run should be submitted")

        async def get_run(self, run_id: str) -> None:  # pragma: no cover
            return None

    return fastapi, create_app(store, NoopEngine(), plugins=plugins)


def test_create_endpoint_provisions_chief(tmp_path: Path) -> None:
    fastapi, app = _make_app(Store(tmp_path / "kyn"))
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        bots = {item["name"] for item in client.get("/api/bots").json()}
    assert CHIEF_NAME in bots


def test_bot_patch_updates_model_and_reports_live(tmp_path: Path) -> None:
    store = Store(tmp_path / "kyn")
    store.put_bot(Bot(name="builder", cwd=str(tmp_path), model="old"))
    fastapi, app = _make_app(store)
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.patch("/api/bots/builder", json={"model": "claude-x"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["model"] == "claude-x"
        assert payload["applied_live"] is False  # NoopEngine has no live switch

        read = client.patch("/api/bots/builder", json={}).json()
        assert read["model"] == "claude-x"

        missing = client.patch("/api/bots/ghost", json={"model": "m"})
        assert missing.status_code == 404


def test_bot_delete_removes_bot_and_routines(tmp_path: Path) -> None:
    from kyn.routines import RoutineStore

    store = Store(tmp_path / "kyn")
    store.put_bot(Bot(name="builder", cwd=str(tmp_path)))
    routines = RoutineStore(store)
    routines.create(
        name="nightly",
        bot_name="builder",
        prompt="check",
        trigger_kind="interval",
        interval_seconds=3600,
        enabled=True,
    )
    fastapi, app = _make_app(store)
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.delete("/api/bots/builder")
        assert response.status_code == 200
        assert response.json() == {"deleted": True, "name": "builder"}
        assert client.get("/api/bots/builder").status_code == 404
        assert [r for r in client.get("/api/routines").json() if r.get("bot_name") == "builder"] == []

        again = client.delete("/api/bots/builder")
        assert again.status_code == 404


def test_delete_bot_goes_through_fleet_tool(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "kyn")
    store.put_bot(Bot(name="worker", cwd=str(tmp_path)))
    fastapi, app = _make_app(store)
    from fastapi.testclient import TestClient

    monkeypatch.setenv("KYN_CONTROL_URL", "http://127.0.0.1:1")  # never contacted
    with TestClient(app) as client:
        # create then delete through the same HTTP surface the MCP drives
        created = client.post(
            "/api/bots", json={"name": "temp", "cwd": str(tmp_path), "engine": "kiro"}
        )
        assert created.status_code == 201
        response = client.delete("/api/bots/temp")
        assert response.status_code == 200
        assert response.json()["deleted"] is True
