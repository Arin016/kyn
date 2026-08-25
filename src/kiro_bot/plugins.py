"""Persistent, capability-scoped MCP server registry.

The registry stores *references* to environment variables, never their values.
References are resolved only while compiling the ``mcpServers`` array for an
ACP ``session/new``/``session/load`` request.  Callers must treat that compiled
array as ephemeral launch material and must not persist or log it.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import PurePath
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, unquote, urlsplit

from .store import Store


_SERVER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_BARE_COMMAND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,255}$")
_TOOL_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9@._:/-]{0,127}$")
_SHELL_META_RE = re.compile(r"[\s;&|`$<>\r\n\x00]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?key|secret|token|password|passwd|credential|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE_RES = (
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:sk|pk)-(?:live|test)-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    re.compile(r"\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)
_SHELL_PROGRAMS = frozenset(
    {"sh", "bash", "dash", "zsh", "fish", "ksh", "csh", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh"}
)
_PLUGIN_FIELDS = frozenset({"name", "transport", "command", "args", "url", "env", "enabled"})
_DEFAULT_TIMEOUT_MS = 60_000
_MAX_TIMEOUT_MS = 3_600_000


class PluginRegistryError(ValueError):
    """Base error for invalid registry operations."""


class PluginNotFoundError(PluginRegistryError):
    pass


class PluginConflictError(PluginRegistryError):
    pass


class SecretResolutionError(PluginRegistryError):
    """A referenced environment variable was absent at launch time."""


@dataclass(frozen=True, slots=True)
class Plugin:
    id: str
    name: str
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def summary(self) -> dict[str, Any]:
        """JSON-safe persisted configuration; contains references, not secrets."""
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.transport == "stdio":
            result.update(
                {
                    "command": self.command,
                    "args": list(self.args),
                    "env": dict(sorted(self.env.items())),
                }
            )
        else:
            result["url"] = self.url
        return result


@dataclass(frozen=True, slots=True)
class BotPluginBinding:
    bot_name: str
    plugin_id: str
    enabled: bool = True
    allow_tools: tuple[str, ...] = ("*",)
    deny_tools: tuple[str, ...] = ()
    auto_approve_tools: tuple[str, ...] = ()
    timeout_ms: int = _DEFAULT_TIMEOUT_MS
    created_at: str = ""
    updated_at: str = ""

    def allows(self, tool_name: str) -> bool:
        """Return the effective policy decision. Deny always has precedence."""
        if not self.enabled:
            return False
        if "*" in self.deny_tools or tool_name in self.deny_tools:
            return False
        return "*" in self.allow_tools or tool_name in self.allow_tools

    def summary(self) -> dict[str, Any]:
        return {
            "bot_name": self.bot_name,
            "plugin_id": self.plugin_id,
            "enabled": self.enabled,
            "allow_tools": list(self.allow_tools),
            "deny_tools": list(self.deny_tools),
            "auto_approve_tools": list(self.auto_approve_tools),
            "timeout_ms": self.timeout_ms,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PluginRegistry:
    """SQLite-backed MCP catalog and per-bot capability bindings."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._migrate()

    # -- plugin CRUD -----------------------------------------------------

    def create_plugin(
        self,
        plugin: Plugin | None = None,
        *,
        plugin_id: str = "",
        name: str = "",
        transport: str = "",
        command: str = "",
        args: Sequence[str] | None = None,
        url: str = "",
        env: Mapping[str, str] | None = None,
        enabled: bool = True,
    ) -> Plugin:
        if plugin is not None:
            if any((plugin_id, name, transport, command, args, url, env)) or enabled is not True:
                raise PluginRegistryError("pass either a Plugin or plugin fields, not both")
            candidate = plugin
        else:
            candidate = Plugin(
                id=plugin_id,
                name=name,
                transport=transport,
                command=command,
                args=tuple(args or ()),
                url=url,
                env=dict(env or {}),
                enabled=enabled,
            )
        candidate = _validate_plugin(candidate)
        now = _now(self.store)
        created = replace(candidate, created_at=now, updated_at=now)
        try:
            with self.store.connect() as db:
                db.execute(
                    """
                    INSERT INTO plugins(
                        id, name, transport, command, args_json, url, env_json,
                        enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _plugin_values(created),
                )
        except sqlite3.IntegrityError as exc:
            raise PluginConflictError(f"plugin {created.id!r} already exists") from exc
        return created

    def get_plugin(self, plugin_id: str) -> Plugin | None:
        _validate_server_id(plugin_id)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        return _plugin_from_row(row) if row else None

    def require_plugin(self, plugin_id: str) -> Plugin:
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            raise PluginNotFoundError(f"plugin {plugin_id!r} does not exist")
        return plugin

    def list_plugins(self, *, enabled_only: bool = False) -> list[Plugin]:
        query = "SELECT * FROM plugins"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY id"
        with self.store.connect() as db:
            rows = db.execute(query).fetchall()
        return [_plugin_from_row(row) for row in rows]

    def update_plugin(self, plugin_id: str, **changes: Any) -> Plugin:
        unknown = set(changes) - _PLUGIN_FIELDS
        if unknown:
            raise PluginRegistryError(f"unknown plugin fields: {', '.join(sorted(unknown))}")
        current = self.require_plugin(plugin_id)
        candidate = replace(
            current,
            **{
                **changes,
                "args": tuple(changes["args"]) if "args" in changes else current.args,
                "env": dict(changes["env"]) if "env" in changes else current.env,
            },
        )
        candidate = _validate_plugin(candidate)
        updated = replace(candidate, created_at=current.created_at, updated_at=_now(self.store))
        with self.store.connect() as db:
            bot_rows = db.execute(
                "SELECT bot_name FROM bot_plugins WHERE plugin_id = ?", (plugin_id,)
            ).fetchall()
            db.execute(
                """
                UPDATE plugins SET name = ?, transport = ?, command = ?,
                    args_json = ?, url = ?, env_json = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    updated.transport,
                    updated.command,
                    json.dumps(list(updated.args)),
                    updated.url,
                    json.dumps(updated.env, sort_keys=True),
                    int(updated.enabled),
                    updated.updated_at,
                    updated.id,
                ),
            )
            _bump_generations(db, (str(row["bot_name"]) for row in bot_rows))
        return updated

    def delete_plugin(self, plugin_id: str) -> None:
        _validate_server_id(plugin_id)
        with self.store.connect() as db:
            bot_rows = db.execute(
                "SELECT bot_name FROM bot_plugins WHERE plugin_id = ?", (plugin_id,)
            ).fetchall()
            cursor = db.execute("DELETE FROM plugins WHERE id = ?", (plugin_id,))
            if cursor.rowcount:
                _bump_generations(db, (str(row["bot_name"]) for row in bot_rows))
        if cursor.rowcount == 0:
            raise PluginNotFoundError(f"plugin {plugin_id!r} does not exist")

    # -- bot bindings ----------------------------------------------------

    def bind_plugin(
        self,
        bot_name: str,
        plugin_id: str,
        *,
        enabled: bool = True,
        allow_tools: Sequence[str] = ("*",),
        deny_tools: Sequence[str] = (),
        auto_approve_tools: Sequence[str] = (),
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> BotPluginBinding:
        plugin = self.require_plugin(plugin_id)
        del plugin  # existence is the capability boundary; the FK is defense in depth
        _require_bot(self.store, bot_name)
        allow, deny, auto = _validate_tool_policy(allow_tools, deny_tools, auto_approve_tools)
        timeout = _validate_timeout(timeout_ms)
        now = _now(self.store)
        with self.store.connect() as db:
            existing = db.execute(
                "SELECT created_at FROM bot_plugins WHERE bot_name = ? AND plugin_id = ?",
                (bot_name, plugin_id),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            db.execute(
                """
                INSERT INTO bot_plugins(
                    bot_name, plugin_id, enabled, allow_tools_json, deny_tools_json,
                    auto_approve_tools_json, timeout_ms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_name, plugin_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    allow_tools_json = excluded.allow_tools_json,
                    deny_tools_json = excluded.deny_tools_json,
                    auto_approve_tools_json = excluded.auto_approve_tools_json,
                    timeout_ms = excluded.timeout_ms,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_name,
                    plugin_id,
                    int(bool(enabled)),
                    json.dumps(list(allow)),
                    json.dumps(list(deny)),
                    json.dumps(list(auto)),
                    timeout,
                    created_at,
                    now,
                ),
            )
            _bump_generations(db, (bot_name,))
        return BotPluginBinding(
            bot_name=bot_name,
            plugin_id=plugin_id,
            enabled=bool(enabled),
            allow_tools=allow,
            deny_tools=deny,
            auto_approve_tools=auto,
            timeout_ms=timeout,
            created_at=created_at,
            updated_at=now,
        )

    def get_binding(self, bot_name: str, plugin_id: str) -> BotPluginBinding | None:
        _validate_bot_name(bot_name)
        _validate_server_id(plugin_id)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM bot_plugins WHERE bot_name = ? AND plugin_id = ?",
                (bot_name, plugin_id),
            ).fetchone()
        return _binding_from_row(row) if row else None

    def list_bindings(self, bot_name: str, *, enabled_only: bool = False) -> list[BotPluginBinding]:
        _validate_bot_name(bot_name)
        query = "SELECT * FROM bot_plugins WHERE bot_name = ?"
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY plugin_id"
        with self.store.connect() as db:
            rows = db.execute(query, (bot_name,)).fetchall()
        return [_binding_from_row(row) for row in rows]

    def unbind_plugin(self, bot_name: str, plugin_id: str) -> None:
        _validate_bot_name(bot_name)
        _validate_server_id(plugin_id)
        with self.store.connect() as db:
            cursor = db.execute(
                "DELETE FROM bot_plugins WHERE bot_name = ? AND plugin_id = ?",
                (bot_name, plugin_id),
            )
            if cursor.rowcount:
                _bump_generations(db, (bot_name,))
        if cursor.rowcount == 0:
            raise PluginNotFoundError(f"plugin {plugin_id!r} is not bound to bot {bot_name!r}")

    def tool_allowed(self, bot_name: str, plugin_id: str, tool_name: str) -> bool:
        _validate_tool_name(tool_name, wildcard=False)
        plugin = self.get_plugin(plugin_id)
        binding = self.get_binding(bot_name, plugin_id)
        return bool(plugin and plugin.enabled and binding and binding.allows(tool_name))

    def tool_auto_approved(self, bot_name: str, plugin_id: str, tool_name: str) -> bool:
        """Return the binding's auto-approval intent, never a final policy decision.

        The caller must still intersect this with global governance.  It is not
        emitted into Kiro's MCP config because backend-side ``autoApprove``
        bypasses the host permission and governance path entirely.
        """
        _validate_tool_name(tool_name, wildcard=False)
        plugin = self.get_plugin(plugin_id)
        binding = self.get_binding(bot_name, plugin_id)
        return bool(
            plugin
            and plugin.enabled
            and binding
            and binding.allows(tool_name)
            and tool_name in binding.auto_approve_tools
        )

    def config_generation(self, bot_name: str) -> int:
        """Monotonic generation for the bot's effective plugin launch config."""
        _require_bot(self.store, bot_name)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT generation FROM plugin_config_generations WHERE bot_name = ?",
                (bot_name,),
            ).fetchone()
        return int(row["generation"]) if row else 0

    # -- launch compilation and safe views -------------------------------

    def compile_session_servers(
        self,
        bot_name: str,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Compile ephemeral ACP entries, resolving all secret refs atomically.

        If any required reference is missing this raises before returning any
        server list.  The returned value can contain resolved secrets in stdio
        ``env`` pairs and therefore must never be written to storage or logs.
        """
        _generation, servers = self.compile_session_configuration(
            bot_name, environ=environ
        )
        return servers

    def compile_session_configuration(
        self,
        bot_name: str,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return one consistent ``(generation, mcpServers)`` snapshot."""
        _require_bot(self.store, bot_name)
        source_env = os.environ if environ is None else environ
        with self.store.connect() as db:
            # Keep the generation and binding rows in one read snapshot so an
            # orchestrator can prove which configuration its ACP session uses.
            db.execute("BEGIN")
            generation_row = db.execute(
                "SELECT generation FROM plugin_config_generations WHERE bot_name = ?",
                (bot_name,),
            ).fetchone()
            rows = db.execute(
                """
                SELECT p.*, b.bot_name, b.enabled AS binding_enabled,
                       b.allow_tools_json, b.deny_tools_json,
                       b.auto_approve_tools_json, b.timeout_ms,
                       b.created_at AS binding_created_at,
                       b.updated_at AS binding_updated_at
                FROM bot_plugins b
                JOIN plugins p ON p.id = b.plugin_id
                WHERE b.bot_name = ? AND b.enabled = 1 AND p.enabled = 1
                ORDER BY p.id
                """,
                (bot_name,),
            ).fetchall()
        generation = int(generation_row["generation"]) if generation_row else 0
        compiled: list[dict[str, Any]] = []
        for row in rows:
            plugin = _plugin_from_row(row)
            binding = BotPluginBinding(
                bot_name=str(row["bot_name"]),
                plugin_id=plugin.id,
                enabled=bool(row["binding_enabled"]),
                allow_tools=tuple(json.loads(row["allow_tools_json"])),
                deny_tools=tuple(json.loads(row["deny_tools_json"])),
                auto_approve_tools=tuple(json.loads(row["auto_approve_tools_json"])),
                timeout_ms=int(row["timeout_ms"]),
                created_at=str(row["binding_created_at"]),
                updated_at=str(row["binding_updated_at"]),
            )
            server: dict[str, Any] = {"name": plugin.id}
            if plugin.transport == "stdio":
                resolved_env = []
                for target_name, reference in sorted(plugin.env.items()):
                    source_name = reference.removeprefix("env:")
                    if source_name not in source_env:
                        raise SecretResolutionError(
                            f"plugin {plugin.id!r} requires environment variable {source_name!r}"
                        )
                    resolved_env.append({"name": target_name, "value": str(source_env[source_name])})
                server.update(
                    {
                        "type": "stdio",
                        "command": plugin.command,
                        "args": list(plugin.args),
                        "env": resolved_env,
                    }
                )
            else:
                server.update({"type": "http", "url": plugin.url})

            # Kiro accepts these server-scoped policy keys on injected ACP
            # entries. A deny is emitted even when the same name was allowed;
            # the registry's permission check applies the same deny-first rule.
            if binding.deny_tools:
                server["disabledTools"] = list(binding.deny_tools)
            server["timeout"] = binding.timeout_ms
            compiled.append(server)
        return generation, compiled

    def plugin_summaries(self) -> list[dict[str, Any]]:
        return [plugin.summary() for plugin in self.list_plugins()]

    def binding_summaries(self, bot_name: str) -> list[dict[str, Any]]:
        return [binding.summary() for binding in self.list_bindings(bot_name)]

    def _migrate(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS plugins (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    transport TEXT NOT NULL CHECK(transport IN ('stdio', 'http')),
                    command TEXT NOT NULL DEFAULT '',
                    args_json TEXT NOT NULL DEFAULT '[]',
                    url TEXT NOT NULL DEFAULT '',
                    env_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_plugins (
                    bot_name TEXT NOT NULL REFERENCES bots(name) ON DELETE CASCADE,
                    plugin_id TEXT NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    allow_tools_json TEXT NOT NULL DEFAULT '["*"]',
                    deny_tools_json TEXT NOT NULL DEFAULT '[]',
                    auto_approve_tools_json TEXT NOT NULL DEFAULT '[]',
                    timeout_ms INTEGER NOT NULL DEFAULT 60000,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(bot_name, plugin_id)
                );
                CREATE INDEX IF NOT EXISTS idx_bot_plugins_plugin
                    ON bot_plugins(plugin_id);
                CREATE TABLE IF NOT EXISTS plugin_config_generations (
                    bot_name TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0)
                );
                """
            )


def _validate_plugin(plugin: Plugin) -> Plugin:
    _validate_server_id(plugin.id)
    _validate_display_name(plugin.name)
    if plugin.transport not in {"stdio", "http"}:
        raise PluginRegistryError("transport must be 'stdio' or 'http'")
    if not isinstance(plugin.enabled, bool):
        raise PluginRegistryError("enabled must be a boolean")
    args = _validate_args(plugin.args)
    env = _validate_env(plugin.env)
    if plugin.transport == "stdio":
        command = _validate_command(plugin.command)
        if plugin.url:
            raise PluginRegistryError("stdio plugins cannot define a URL")
        return replace(plugin, command=command, args=args, url="", env=env)
    if plugin.command or args:
        raise PluginRegistryError("HTTP plugins cannot define a command or args")
    if env:
        raise PluginRegistryError("HTTP plugins cannot define process environment variables")
    return replace(plugin, command="", args=(), url=_validate_url(plugin.url), env={})


def _validate_server_id(value: str) -> None:
    if not isinstance(value, str) or not _SERVER_ID_RE.fullmatch(value):
        raise PluginRegistryError(
            "plugin id/server name must be 1-64 characters using letters, digits, '.', '_' or '-'"
        )


def _validate_display_name(value: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 100:
        raise PluginRegistryError("plugin name must be 1-100 trimmed characters")
    if _CONTROL_RE.search(value):
        raise PluginRegistryError("plugin name cannot contain control characters")


def _validate_bot_name(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 200 or _CONTROL_RE.search(value):
        raise PluginRegistryError("invalid bot name")


def _require_bot(store: Store, bot_name: str) -> None:
    _validate_bot_name(bot_name)
    with store.connect() as db:
        present = db.execute("SELECT 1 FROM bots WHERE name = ?", (bot_name,)).fetchone()
    if not present:
        raise PluginNotFoundError(f"bot {bot_name!r} does not exist")


def _validate_command(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise PluginRegistryError("stdio command must be a non-empty executable name or absolute path")
    if _SHELL_META_RE.search(value):
        raise PluginRegistryError("stdio command must be one executable, not a shell string")
    path = PurePath(value)
    if path.name.casefold() in _SHELL_PROGRAMS:
        raise PluginRegistryError("shell interpreters are not accepted as MCP commands")
    if path.is_absolute():
        if ".." in path.parts or value != str(path):
            raise PluginRegistryError("command path must be an absolute normalized path")
    elif "/" in value or "\\" in value or not _BARE_COMMAND_RE.fullmatch(value):
        raise PluginRegistryError("command must be a safe bare executable name or absolute path")
    return value


def _validate_args(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise PluginRegistryError("args must be an argv list, never a shell string")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or len(value) > 4096 or _CONTROL_RE.search(value):
            raise PluginRegistryError("every argv item must be a control-free string")
        option_key = value.split("=", 1)[0] if value.startswith("-") else ""
        if (option_key and _SECRET_KEY_RE.search(option_key)) or _looks_like_secret(value):
            raise PluginRegistryError("possible plaintext secret in args; pass secrets through env references")
        result.append(value)
    if len(result) > 256:
        raise PluginRegistryError("args cannot contain more than 256 items")
    return tuple(result)


def _validate_env(values: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise PluginRegistryError("env must map variable names to env:NAME references")
    result: dict[str, str] = {}
    for target, reference in values.items():
        if not isinstance(target, str) or not _ENV_NAME_RE.fullmatch(target):
            raise PluginRegistryError("environment keys must be valid variable names")
        if not isinstance(reference, str) or not reference.startswith("env:"):
            detail = "secret" if _SECRET_KEY_RE.search(target) or _looks_like_secret(str(reference)) else "value"
            raise PluginRegistryError(
                f"inline environment {detail}s are forbidden; use env:NAME references"
            )
        source = reference[4:]
        if not _ENV_NAME_RE.fullmatch(source):
            raise PluginRegistryError("environment references must have the form env:VALID_NAME")
        result[target] = f"env:{source}"
    if len(result) > 128:
        raise PluginRegistryError("env cannot contain more than 128 entries")
    return result


def _validate_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or _CONTROL_RE.search(value):
        raise PluginRegistryError("HTTP plugin URL is invalid")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise PluginRegistryError("HTTP plugin URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise PluginRegistryError("credentials are forbidden in plugin URLs")
    try:
        parsed.port
    except ValueError as exc:
        raise PluginRegistryError("HTTP plugin URL has an invalid port") from exc
    if parsed.scheme == "http" and not _is_localhost(parsed.hostname):
        raise PluginRegistryError("remote MCP URLs require HTTPS; HTTP is allowed only for localhost")
    decoded_path = unquote(parsed.path)
    if "\\" in decoded_path or _CONTROL_RE.search(decoded_path):
        raise PluginRegistryError("HTTP plugin URL path is invalid")
    if any(part in {".", ".."} for part in decoded_path.split("/")):
        raise PluginRegistryError("HTTP plugin URL path cannot contain dot segments")
    if parsed.fragment:
        raise PluginRegistryError("HTTP plugin URL cannot contain a fragment")
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if _SECRET_KEY_RE.search(key) or _looks_like_secret(item):
            raise PluginRegistryError("possible plaintext secret in URL query")
    return value


def _is_localhost(host: str) -> bool:
    normalized = host.rstrip(".").casefold()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_tool_policy(
    allow_tools: Sequence[str],
    deny_tools: Sequence[str],
    auto_approve_tools: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    allow = _normalize_tools(allow_tools, wildcard=True, label="allow_tools")
    deny = _normalize_tools(deny_tools, wildcard=True, label="deny_tools")
    auto = _normalize_tools(auto_approve_tools, wildcard=False, label="auto_approve_tools")
    if not allow:
        raise PluginRegistryError("allow_tools cannot be empty; use explicit tools or '*'")
    for tool in auto:
        if "*" not in allow and tool not in allow:
            raise PluginRegistryError("every auto-approved tool must be included in allow_tools")
        if "*" in deny or tool in deny:
            raise PluginRegistryError("an auto-approved tool cannot also be denied")
    return allow, deny, auto


def _normalize_tools(values: Sequence[str], *, wildcard: bool, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise PluginRegistryError(f"{label} must be a list of tool names")
    result: list[str] = []
    for value in values:
        _validate_tool_name(value, wildcard=wildcard)
        if value not in result:
            result.append(value)
    return tuple(result)


def _validate_tool_name(value: str, *, wildcard: bool) -> None:
    if value == "*":
        if wildcard:
            return
        raise PluginRegistryError("auto-approved tools must be explicit; wildcards are forbidden")
    if not isinstance(value, str) or not _TOOL_RE.fullmatch(value) or any(c in value for c in "*?[]{}"):
        raise PluginRegistryError("invalid tool name or wildcard")


def _validate_timeout(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PluginRegistryError("timeout_ms must be an integer")
    if value < 1_000 or value > _MAX_TIMEOUT_MS:
        raise PluginRegistryError("timeout_ms must be between 1000 and 3600000")
    return value


def _looks_like_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_RES)


def _plugin_values(plugin: Plugin) -> tuple[Any, ...]:
    return (
        plugin.id,
        plugin.name,
        plugin.transport,
        plugin.command,
        json.dumps(list(plugin.args)),
        plugin.url,
        json.dumps(plugin.env, sort_keys=True),
        int(plugin.enabled),
        plugin.created_at,
        plugin.updated_at,
    )


def _plugin_from_row(row: sqlite3.Row) -> Plugin:
    return Plugin(
        id=str(row["id"]),
        name=str(row["name"]),
        transport=str(row["transport"]),
        command=str(row["command"]),
        args=tuple(json.loads(row["args_json"])),
        url=str(row["url"]),
        env=dict(json.loads(row["env_json"])),
        enabled=bool(row["enabled"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _binding_from_row(row: sqlite3.Row) -> BotPluginBinding:
    return BotPluginBinding(
        bot_name=str(row["bot_name"]),
        plugin_id=str(row["plugin_id"]),
        enabled=bool(row["enabled"]),
        allow_tools=tuple(json.loads(row["allow_tools_json"])),
        deny_tools=tuple(json.loads(row["deny_tools_json"])),
        auto_approve_tools=tuple(json.loads(row["auto_approve_tools_json"])),
        timeout_ms=int(row["timeout_ms"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _bump_generations(db: sqlite3.Connection, bot_names: Any) -> None:
    """Bump each affected bot once inside the caller's config transaction."""
    names = sorted(set(str(name) for name in bot_names))
    db.executemany(
        """
        INSERT INTO plugin_config_generations(bot_name, generation)
        VALUES (?, 1)
        ON CONFLICT(bot_name) DO UPDATE SET generation = generation + 1
        """,
        ((name,) for name in names),
    )


def _now(store: Store) -> str:
    # Reuse SQLite's clock so all writers sharing Store.connect use one format
    # and no secret-bearing launch material crosses this persistence boundary.
    with store.connect() as db:
        row = db.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now') AS now").fetchone()
    return str(row["now"])
