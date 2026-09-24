"""Plugin Place: curated MCP servers operators can install for their bots.

Each template describes a real, known-good MCP server (command or URL), the
configuration it needs, and which of those are secrets. Installing creates
the plugin (idempotent) and binds it to the named bots in *ask mode*
(``allow=["*"]``, ``auto_approve=[]``): the first tool use raises a normal
approval gate, so bots adopt tools by asking the operator — never silently.

Secrets (tokens, connection strings marked secret) go to the managed vault,
never into chat, args, or stored env maps. Non-secret config substitutes
``{KEY}`` placeholders in args/env at install time.
"""

from __future__ import annotations

import os
import re
from typing import Any, Mapping, Sequence

from .plugins import PluginRegistry
from .store import Store

__all__ = [
    "PlaceError",
    "TEMPLATES",
    "catalog_view",
    "get_template",
    "install_template",
    "missing_secrets",
]

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class PlaceError(RuntimeError):
    pass


def _template(
    *,
    id: str,
    name: str,
    blurb: str,
    docs_url: str,
    transport: str,
    command: str = "",
    args: Sequence[str] = (),
    url: str = "",
    env: Mapping[str, str] | None = None,
    config_schema: Sequence[Mapping[str, Any]] | None = None,
    required_secrets: Sequence[str] = (),
    warning: str = "",
) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "blurb": blurb,
        "docs_url": docs_url,
        "transport": transport,
        "command": command,
        "args": list(args),
        "url": url,
        "env": dict(env or {}),
        "config_schema": [dict(item) for item in (config_schema or [])],
        "required_secrets": list(required_secrets),
        "warning": warning,
    }


def _config(
    key: str,
    label: str,
    *,
    required: bool = False,
    secret: bool = False,
    placeholder: str = "",
    hint: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "required": required,
        "secret": secret,
        "placeholder": placeholder,
        "hint": hint,
    }


TEMPLATES: tuple[dict[str, Any], ...] = (
    _template(
        id="gitlab",
        name="GitLab",
        blurb="Issues, merge requests, pipelines and files for a GitLab host.",
        docs_url="https://github.com/modelcontextprotocol/servers",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-gitlab"],
        env={
            "GITLAB_PERSONAL_ACCESS_TOKEN": "env:GITLAB_PERSONAL_ACCESS_TOKEN",
            "GITLAB_API_URL": "env:GITLAB_HOST_URL",
        },
        config_schema=[
            _config(
                "GITLAB_PERSONAL_ACCESS_TOKEN",
                "Personal access token",
                required=True,
                secret=True,
                hint="Needs api scope. Paste it in the secrets field — never in chat.",
            ),
            _config(
                "GITLAB_HOST_URL",
                "GitLab host URL",
                placeholder="https://gitlab.com",
                hint="Empty means gitlab.com.",
            ),
        ],
        required_secrets=["GITLAB_PERSONAL_ACCESS_TOKEN"],
    ),
    _template(
        id="github",
        name="GitHub",
        blurb="Repos, issues, pull requests and search across GitHub.",
        docs_url="https://github.com/modelcontextprotocol/servers",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "env:GITHUB_PERSONAL_ACCESS_TOKEN"},
        config_schema=[
            _config(
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "Personal access token",
                required=True,
                secret=True,
                hint="Classic or fine-grained token with repo scope.",
            ),
        ],
        required_secrets=["GITHUB_PERSONAL_ACCESS_TOKEN"],
    ),
    _template(
        id="atlassian",
        name="Jira + Confluence",
        blurb="Jira issues and Confluence pages via the Atlassian MCP server.",
        docs_url="https://github.com/sooperset/mcp-atlassian",
        transport="stdio",
        command="uvx",
        args=["mcp-atlassian"],
        env={
            "JIRA_URL": "env:JIRA_URL",
            "CONFLUENCE_URL": "env:CONFLUENCE_URL",
            "JIRA_USERNAME": "env:JIRA_USERNAME",
            "JIRA_API_TOKEN": "env:JIRA_API_TOKEN",
        },
        config_schema=[
            _config("JIRA_URL", "Jira URL", required=True, placeholder="https://you.atlassian.net"),
            _config("CONFLUENCE_URL", "Confluence URL", placeholder="Same as Jira when empty"),
            _config("JIRA_USERNAME", "Atlassian email", hint="Login email for the API token."),
            _config(
                "JIRA_API_TOKEN",
                "API token",
                required=True,
                secret=True,
                hint="Created at id.atlassian.com — never paste it in chat.",
            ),
        ],
        required_secrets=["JIRA_API_TOKEN"],
    ),
    _template(
        id="slack",
        name="Slack",
        blurb="Read and post to Slack channels the bot is invited to.",
        docs_url="https://github.com/modelcontextprotocol/servers",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={
            "SLACK_BOT_TOKEN": "env:SLACK_BOT_TOKEN",
            "SLACK_TEAM_ID": "env:SLACK_TEAM_ID",
        },
        config_schema=[
            _config("SLACK_BOT_TOKEN", "Bot token", required=True, secret=True, hint="xoxb-… token."),
            _config("SLACK_TEAM_ID", "Team ID", required=True, hint="Starts with T…."),
        ],
        required_secrets=["SLACK_BOT_TOKEN"],
    ),
    _template(
        id="postgres",
        name="Postgres",
        blurb="Run read queries against one Postgres database.",
        docs_url="https://github.com/modelcontextprotocol/servers",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres", "env:DATABASE_URL"],
        config_schema=[
            _config(
                "DATABASE_URL",
                "Connection string",
                required=True,
                secret=True,
                placeholder="postgresql://user:pass@host/db",
            ),
        ],
        required_secrets=["DATABASE_URL"],
        warning=(
            "This server takes the connection string positionally; it is passed "
            "ephemerally at session start and stays out of storage, but it is "
            "visible in the process listing while running. Prefer a read-only role."
        ),
    ),
    _template(
        id="filesystem",
        name="Filesystem",
        blurb="Give bots governed file access to one directory outside their cwd.",
        docs_url="https://github.com/modelcontextprotocol/servers",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "{ALLOWED_DIR}"],
        config_schema=[
            _config(
                "ALLOWED_DIR",
                "Allowed directory",
                required=True,
                placeholder="/Users/you/shared",
                hint="The only directory this server can touch.",
            ),
        ],
        required_secrets=[],
    ),
)


def _by_id(template_id: str) -> dict[str, Any]:
    wanted = str(template_id or "").strip()
    for template in TEMPLATES:
        if template["id"] == wanted:
            return template
    raise PlaceError(f"unknown plugin template {template_id!r}")


def get_template(template_id: str) -> dict[str, Any]:
    """Return a deep copy of one catalog template."""
    import copy

    return copy.deepcopy(_by_id(template_id))


def missing_secrets(
    template: Mapping[str, Any],
    registry: PluginRegistry,
    *,
    plugin_id: str | None = None,
) -> list[str]:
    """Required secret keys with neither vault value nor process env value."""
    pid = plugin_id or str(template.get("id") or "")
    stored = set(registry.secret_names(pid)) if _plugin_exists(registry, pid) else set()
    missing: list[str] = []
    for key in template.get("required_secrets", ()):  # type: ignore[union-attr]
        name = str(key)
        if name in stored or os.environ.get(name, "").strip():
            continue
        missing.append(name)
    return missing


def _plugin_exists(registry: PluginRegistry, plugin_id: str) -> bool:
    try:
        return registry.get_plugin(plugin_id) is not None
    except Exception:
        return False


def catalog_view(registry: PluginRegistry) -> list[dict[str, Any]]:
    """Catalog templates annotated with install + secret status."""
    import copy

    views: list[dict[str, Any]] = []
    for template in TEMPLATES:
        view = copy.deepcopy(template)
        installed = _plugin_exists(registry, template["id"])
        view["installed"] = installed
        view["missing_secrets"] = missing_secrets(template, registry)
        views.append(view)
    return views


def install_template(
    registry: PluginRegistry,
    store: Store,
    template_id: str,
    bot_names: Sequence[str],
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Install a catalog template and bind it to bots in ask mode.

    Idempotent: reinstalling returns the existing plugin. Config values —
    secret or plain — land in the managed vault (never in stored maps);
    ``{KEY}`` placeholders substitute into argv only, and only for
    non-secret keys. Bindings always land as allow-all/ask-first so the first
    tool use raises an approval gate for the operator.
    """
    template = _by_id(template_id)
    names = [str(name).strip() for name in (bot_names or []) if str(name).strip()]
    if not names:
        raise PlaceError("name at least one bot to bind the plugin to")
    for name in names:
        if store.get_bot(name) is None:
            raise PlaceError(f"bot {name!r} does not exist")
    values = {str(key): str(config.get(key) or "") for key in (config or {})}
    schema = {str(item.get("key") or ""): item for item in template["config_schema"]}
    for key in values:
        if key not in schema:
            raise PlaceError(f"unknown config key {key!r} for template {template['id']!r}")
    secret_keys = {key for key, item in schema.items() if item.get("secret")}
    applied: dict[str, str] = {}
    for key, item in schema.items():
        value = values.get(key, "").strip()
        # Required non-secrets block the install; required secrets may come
        # later (Plugin Place secrets field or daemon env) and are reported
        # as missing instead.
        if item.get("required") and not value and key not in secret_keys:
            raise PlaceError(f"config {key!r} is required")
        if value:
            applied[key] = value

    def substitute(text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key in secret_keys:
                raise PlaceError(
                    f"config {key!r} is a secret: it goes to the vault, "
                    "never into commands"
                )
            return applied.get(key, "")

        return _PLACEHOLDER_RE.sub(replace, text)

    for target, raw in template["env"].items():
        if not str(raw).startswith("env:"):
            raise PlaceError(f"template {template['id']!r} has a non-reference env value")
    args = [substitute(str(part)) for part in template["args"]]
    if any(not part for part in args):
        raise PlaceError("a required config value is missing for the server command")
    # Optional config left empty (and absent from the daemon environment) is
    # dropped so the server's own defaults apply instead of an empty value.
    optional = {
        str(item.get("key") or "")
        for item in template["config_schema"]
        if not item.get("required")
    }
    env: dict[str, str] = {}
    for target, raw in template["env"].items():
        source = str(raw).removeprefix("env:")
        if (
            source in optional
            and source not in applied
            and not os.environ.get(source, "").strip()
        ):
            continue
        env[str(target)] = str(raw)

    plugin_id = str(template["id"])
    existing = registry.get_plugin(plugin_id)
    if existing is None:
        registry.create_plugin(
            plugin_id=plugin_id,
            name=str(template["name"]),
            transport=str(template["transport"]),
            command=str(template["command"]),
            args=args,
            url=str(template["url"]),
            env=env,
        )
    for key, value in applied.items():
        registry.set_secret(plugin_id, key, value)
    bindings = []
    for name in names:
        bindings.append(
            registry.bind_plugin(
                name,
                plugin_id,
                enabled=True,
                allow_tools=("*",),
                deny_tools=(),
                auto_approve_tools=(),
            ).summary()
        )
    return {
        "plugin_id": plugin_id,
        "bindings": bindings,
        "applied_config": sorted(applied),
        "missing_secrets": missing_secrets(template, registry, plugin_id=plugin_id),
    }
