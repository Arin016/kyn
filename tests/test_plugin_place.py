from __future__ import annotations

from pathlib import Path

import pytest

from kyn.concierge import CONCIERGE_BRIEF, CONCIERGE_NAME, concierge_exists, ensure_concierge
from kyn.delegation_guard import authorize
from kyn.harness_context import compose_execution_prompt, display_prompt
from kyn.plugin_place import (
    PlaceError,
    TEMPLATES,
    catalog_view,
    get_template,
    install_template,
    missing_secrets,
)
from kyn.plugins import PluginNotFoundError, PluginRegistry, PluginRegistryError, SecretResolutionError
from kyn.store import Bot, Store


def _registry(tmp_path: Path) -> tuple[Store, PluginRegistry]:
    store = Store(tmp_path / "store")
    return store, PluginRegistry(store)


def _bot(store: Store, name: str, tmp_path: Path) -> None:
    if store.get_bot(name) is None:
        store.put_bot(Bot(name=name, cwd=str(tmp_path)))


# ---- catalog integrity -----------------------------------------------------


def test_catalog_has_six_unique_wellformed_templates() -> None:
    assert len(TEMPLATES) == 6
    ids = [template["id"] for template in TEMPLATES]
    assert len(set(ids)) == len(ids)
    for template in TEMPLATES:
        assert template["name"] and template["blurb"] and template["docs_url"]
        assert template["transport"] == "stdio"
        assert template["command"] in {"npx", "uvx"}
        assert template["args"]
        for key, item in ((item.get("key") or "", item) for item in template["config_schema"]):
            assert key and item.get("label")
        for secret in template["required_secrets"]:
            assert secret in {str(item.get("key") or "") for item in template["config_schema"]}
        assert get_template(template["id"])["id"] == template["id"]
    with pytest.raises(PlaceError):
        get_template("does-not-exist")


def test_catalog_templates_pass_registry_validation(tmp_path: Path) -> None:
    """Every template must be installable as-is (no execution, just validation)."""
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    for template in TEMPLATES:
        config = {}
        for item in template["config_schema"]:
            key = str(item.get("key") or "")
            if not item.get("required"):
                continue
            config[key] = f"SECRET-FOR-{key}" if item.get("secret") else f"VALUE-FOR-{key}"
        # Filesystem needs a real dir only at session start, not at install.
        result = install_template(registry, store, template["id"], ["scout"], config)
        assert result["plugin_id"] == template["id"]
        assert result["bindings"][0]["auto_approve_tools"] == []
        plugin = registry.get_plugin(template["id"])
        assert plugin is not None
        summary = plugin.summary()
        blob = str(summary)
        for key, item in ((i.get("key") or "", i) for i in template["config_schema"]):
            if item.get("secret") and key in config:
                # Secret values never land in stored maps or summaries.
                assert f"SECRET-FOR-{key}" not in blob


# ---- secrets vault ---------------------------------------------------------


def test_vault_round_trip_names_only_and_delete(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    registry.create_plugin(plugin_id="p", name="P", transport="http", url="https://x.example")
    registry.set_secret("p", "TOKEN", "s3cr3t")
    assert registry.secret_names("p") == ["TOKEN"]
    with pytest.raises(PluginRegistryError):
        registry.set_secret("p", "not a name!", "v")
    with pytest.raises(PluginRegistryError):
        registry.set_secret("p", "EMPTY", "")
    assert registry.delete_secret("p", "TOKEN") is True
    assert registry.delete_secret("p", "TOKEN") is False
    assert registry.secret_names("p") == []
    with pytest.raises(PluginNotFoundError):
        registry.set_secret("ghost", "TOKEN", "v")


def test_vault_beats_process_env_and_summaries_never_leak(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    registry.create_plugin(
        plugin_id="p", name="P", transport="stdio", command="printf",
        args=["hi"], env={"TARGET": "env:VAULT_PROBE"},
    )
    registry.bind_plugin("scout", "p")
    _generation, servers = registry.compile_session_configuration(
        "scout", environ={"VAULT_PROBE": "from-env"}
    )
    assert servers[0]["env"] == [{"name": "TARGET", "value": "from-env"}]
    registry.set_secret("p", "VAULT_PROBE", "from-vault")
    _generation, servers = registry.compile_session_configuration(
        "scout", environ={"VAULT_PROBE": "from-env"}
    )
    assert servers[0]["env"] == [{"name": "TARGET", "value": "from-vault"}]
    assert "from-vault" not in str(registry.get_plugin("p").summary())
    assert "from-vault" not in str(registry.list_plugins())


def test_missing_secret_blocks_session_compile(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    registry.create_plugin(
        plugin_id="p", name="P", transport="stdio", command="printf",
        args=["hi"], env={"TARGET": "env:MISSING_PROBE"},
    )
    registry.bind_plugin("scout", "p")
    with pytest.raises(SecretResolutionError):
        registry.compile_session_configuration("scout", environ={})


def test_env_ref_argv_resolves_ephemerally(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    registry.create_plugin(
        plugin_id="p", name="P", transport="stdio", command="printf",
        args=["-y", "env:DB_URL"], env={},
    )
    registry.bind_plugin("scout", "p")
    registry.set_secret("p", "DB_URL", "postgresql://x")
    _generation, servers = registry.compile_session_configuration("scout", environ={})
    assert servers[0]["args"][-1] == "postgresql://x"
    assert "postgresql://x" not in str(registry.get_plugin("p").summary())


# ---- install flow ----------------------------------------------------------


def test_install_filesystem_end_to_end(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    _bot(store, "writer", tmp_path)
    result = install_template(
        registry, store, "filesystem", ["scout", "writer"], {"ALLOWED_DIR": str(tmp_path)}
    )
    assert result["missing_secrets"] == []
    assert len(result["bindings"]) == 2
    plugin = registry.get_plugin("filesystem")
    assert plugin is not None and plugin.args[-1] == str(tmp_path)
    binding = registry.get_binding("scout", "filesystem")
    assert binding is not None and binding.enabled
    assert binding.allow_tools == ("*",) and binding.auto_approve_tools == ()
    # Idempotent reinstall.
    again = install_template(registry, store, "filesystem", ["scout"], {"ALLOWED_DIR": str(tmp_path)})
    assert again["plugin_id"] == "filesystem"


def test_install_gitlab_routes_token_to_vault(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    result = install_template(
        registry, store, "gitlab", ["scout"],
        {"GITLAB_PERSONAL_ACCESS_TOKEN": "glpat-123", "GITLAB_HOST_URL": "https://git.example"},
    )
    assert result["missing_secrets"] == []
    assert registry.secret_names("gitlab") == ["GITLAB_HOST_URL", "GITLAB_PERSONAL_ACCESS_TOKEN"]
    blob = str(registry.get_plugin("gitlab").summary())
    assert "glpat-123" not in blob
    assert "https://git.example" not in blob


def test_install_reports_missing_secrets_without_blocking(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    result = install_template(registry, store, "gitlab", ["scout"], {})
    assert result["missing_secrets"] == ["GITLAB_PERSONAL_ACCESS_TOKEN"]
    assert registry.get_plugin("gitlab") is not None


def test_install_rejects_bad_input(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    with pytest.raises(PlaceError):
        install_template(registry, store, "nope", ["scout"], {})
    with pytest.raises(PlaceError):
        install_template(registry, store, "filesystem", [], {"ALLOWED_DIR": str(tmp_path)})
    with pytest.raises(PlaceError):
        install_template(registry, store, "filesystem", ["ghost"], {"ALLOWED_DIR": str(tmp_path)})
    with pytest.raises(PlaceError):
        install_template(registry, store, "filesystem", ["scout"], {})
    with pytest.raises(PlaceError):
        install_template(
            registry, store, "filesystem", ["scout"],
            {"ALLOWED_DIR": str(tmp_path), "BOGUS": "x"},
        )


def test_catalog_view_reports_install_and_secrets(tmp_path: Path) -> None:
    store, registry = _registry(tmp_path)
    _bot(store, "scout", tmp_path)
    assert all(not item["installed"] for item in catalog_view(registry))
    install_template(registry, store, "github", ["scout"], {})
    view = {item["id"]: item for item in catalog_view(registry)}
    assert view["github"]["installed"] is True
    assert view["github"]["missing_secrets"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"]
    assert view["filesystem"]["installed"] is False


# ---- guard -----------------------------------------------------------------


def test_guard_gates_install_but_not_catalog() -> None:
    names = ["chief", "scout"]
    allowed, _ = authorize("chief", "plugin_catalog", actor="api", message="hi", bot_names=names)
    assert allowed
    allowed, reason = authorize(
        "scout", "install_catalog_plugin", actor="api", message="do it", bot_names=names
    )
    assert not allowed and "direct chat" in reason
    allowed, _ = authorize(
        "chief", "install_catalog_plugin", actor="api",
        message="@scout install gitlab for us", bot_names=names,
    )
    assert allowed


# ---- concierge --------------------------------------------------------------


def test_concierge_provisions_with_brief_and_bindings(tmp_path: Path) -> None:
    from kyn.chief import FLEET_PLUGIN_ID
    from kyn.internal_control import CONTROL_PLUGIN_ID

    store = Store(tmp_path / "state")
    plugins = PluginRegistry(store)
    bot = ensure_concierge(store, plugins)
    assert bot is not None and bot.name == CONCIERGE_NAME
    assert concierge_exists(store)
    assert bot.brief == CONCIERGE_BRIEF
    fleet = plugins.get_binding(CONCIERGE_NAME, FLEET_PLUGIN_ID)
    assert fleet is not None and "install_catalog_plugin" in fleet.allow_tools
    assert plugins.get_binding(CONCIERGE_NAME, CONTROL_PLUGIN_ID) is not None
    # Idempotent, and an operator-customized brief is never clobbered.
    store.put_bot(Bot(name=CONCIERGE_NAME, cwd=str(tmp_path), brief="mine"))
    assert ensure_concierge(store, plugins) is not None
    assert store.get_bot(CONCIERGE_NAME).brief == "mine"  # type: ignore[union-attr]


def test_concierge_respects_deletion_and_opt_out(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "state")
    plugins = PluginRegistry(store)
    ensure_concierge(store, plugins)
    with store.connect() as db:
        db.execute("DELETE FROM bots WHERE name = ?", (CONCIERGE_NAME,))
    assert ensure_concierge(store, plugins) is None
    monkeypatch.setenv("KYN_NO_CONCIERGE", "1")
    assert ensure_concierge(Store(tmp_path / "other"), PluginRegistry(Store(tmp_path / "other"))) is None


# ---- brief ------------------------------------------------------------------


def test_brief_round_trips_and_renders_in_prompt(tmp_path: Path) -> None:
    store = Store(tmp_path / "state")
    store.put_bot(Bot(name="scout", cwd=str(tmp_path), brief="You are terse."))
    assert store.get_bot("scout").brief == "You are terse."  # type: ignore[union-attr]
    rendered = compose_execution_prompt("hi", bot_names=["scout"], persona="You are terse.")
    assert "<bot_brief>" in rendered and "You are terse." in rendered
    assert display_prompt(rendered) == "hi"
    plain = compose_execution_prompt("hi", bot_names=["scout"])
    assert "<bot_brief>" not in plain


# ---- HTTP routes ------------------------------------------------------------


class _QuietEngine:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _place_client(tmp_path: Path, store: Store | None = None):
    pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    from fastapi.testclient import TestClient

    from kyn.server import create_app

    holding = store or Store(tmp_path / "state")
    return TestClient(create_app(holding, _QuietEngine()))  # type: ignore[arg-type]


def test_place_routes_catalog_install_and_secrets(tmp_path: Path) -> None:
    from kyn.store import Bot as _Bot

    store = Store(tmp_path / "state")
    store.put_bot(_Bot(name="scout", cwd=str(tmp_path)))
    with _place_client(tmp_path, store) as client:
        catalog = client.get("/api/plugin-place/catalog")
        assert catalog.status_code == 200
        assert len(catalog.json()) == 6
        assert all("missing_secrets" in item for item in catalog.json())

        installed = client.post(
            "/api/plugin-place/install",
            json={"template_id": "filesystem", "bot_names": ["scout"], "config": {"ALLOWED_DIR": str(tmp_path)}},
        )
        assert installed.status_code == 201, installed.text
        assert installed.json()["missing_secrets"] == []

        catalog2 = client.get("/api/plugin-place/catalog").json()
        assert [i for i in catalog2 if i["id"] == "filesystem"][0]["installed"] is True

        assert client.post(
            "/api/plugin-place/install",
            json={"template_id": "nope", "bot_names": ["scout"], "config": {}},
        ).status_code == 422
        assert client.post(
            "/api/plugin-place/install",
            json={"template_id": "filesystem", "bot_names": ["ghost"], "config": {"ALLOWED_DIR": str(tmp_path)}},
        ).status_code == 404

        put = client.post(
            "/api/plugins/filesystem/secrets", json={"name": "EXTRA", "value": "shh"}
        )
        assert put.status_code == 201
        names = client.get("/api/plugins/filesystem/secrets").json()
        # ALLOWED_DIR came from install config (plain values live in the vault
        # too); EXTRA was just added.
        assert names["secrets"] == ["ALLOWED_DIR", "EXTRA"]
        assert client.delete("/api/plugins/filesystem/secrets/EXTRA").status_code == 200
        assert client.delete("/api/plugins/filesystem/secrets/EXTRA").status_code == 404
        assert client.get("/api/plugins/ghost/secrets").status_code == 404
        assert client.post(
            "/api/plugins/filesystem/secrets", json={"name": "bad name!", "value": "x"}
        ).status_code == 422


def test_bot_brief_survives_api_round_trip(tmp_path: Path) -> None:
    store = Store(tmp_path / "state")
    with _place_client(tmp_path, store) as client:
        created = client.post(
            "/api/bots", json={"name": "scout", "cwd": str(tmp_path), "brief": "Terse reviewer."}
        )
        assert created.status_code == 201
        assert created.json()["brief"] == "Terse reviewer."
        patched = client.patch("/api/bots/scout", json={"brief": "Verbose reviewer."})
        assert patched.json()["brief"] == "Verbose reviewer."
        assert client.get("/api/bots/scout").json()["brief"] == "Verbose reviewer."


def test_fleet_advertises_place_tools() -> None:
    from kyn.fleet_mcp import _dispatch

    listed = _dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        "http://127.0.0.1:8765",
        "chief",
    )
    assert listed is not None
    names = {item["name"] for item in listed["result"]["tools"]}  # type: ignore[index]
    assert {"plugin_catalog", "install_catalog_plugin"} <= names
