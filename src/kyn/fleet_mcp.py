"""Fleet-control MCP: admin-grade tools for a chief-of-staff bot.

Every named KYN already carries the coordination MCP (:mod:`kyn.control_mcp`)
with ``call_bot`` and team plans. The fleet plugin adds the other half of the
control plane: creating bots, reconfiguring them (model, effort, agent,
working directory), reading and writing their governance policies, managing
routines and MCP plugin bindings, checking fleet health, and running ad-hoc
commands on the host.

A chief-of-staff bot bound to this plugin can therefore do via conversation
anything an operator could do with keyboard and mouse. Safety comes from the
same machinery as everything else: the daemon owns the loopback boundary,
governance still meters the chief's own runs, and destructive surfaces
(delete bot, run command) are explicit tools the operator can see and revoke
by unbinding one plugin.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping


PROTOCOL_VERSION = "2025-06-18"
MAX_TIMEOUT_SECONDS = 600
MAX_OUTPUT_CHARS = 20_000

TOOLS = [
    {
        "name": "fleet_status",
        "description": (
            "One snapshot of the whole KYN fleet: every bot with its engine, model, "
            "working directory, plus active runs and pending approval requests. "
            "Start here before any fleet change."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "create_bot",
        "description": (
            "Create a durable named bot. engine is kiro, opencode, or codex; model is "
            "that engine's model id (see list_engine_models); cwd is an absolute "
            "directory the bot will work in. Name becomes the bot's identity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 64},
                "cwd": {"type": "string"},
                "engine": {"type": "string", "enum": ["kiro", "opencode", "codex"], "default": "kiro"},
                "model": {"type": "string", "default": ""},
                "effort": {"type": "string", "default": ""},
                "agent": {"type": "string", "default": ""},
                "brief": {"type": "string", "default": "", "maxLength": 8000},
            },
            "required": ["name", "cwd"],
            "additionalProperties": False,
        },
    },
    {
        "name": "configure_bot",
        "description": (
            "Reconfigure an existing bot. Only the fields you pass change; everything "
            "else is preserved. model/effort/agent apply to the live session when the "
            "engine supports it. Pass {\"name\": \"x\"} with no other fields to read a "
            "bot's full configuration."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "model": {"type": "string"},
                "effort": {"type": "string"},
                "agent": {"type": "string"},
                "cwd": {"type": "string"},
                "brief": {"type": "string", "maxLength": 8000},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_bot",
        "description": (
            "Permanently delete a named bot, its history, policies, and bindings. "
            "There is no undo. Never call this unless the operator explicitly asked "
            "for deletion of exactly this bot."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_bot_policy",
        "description": (
            "Set a bot's governance policy. approval_mode: ask (default), allowlist, "
            "or deny_all. allowed_tools/denied_tools are tool-name lists; limits are "
            "0 for unlimited."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "approval_mode": {"type": "string", "enum": ["ask", "allowlist", "deny_all"]},
                "allowed_tools": {"type": "array", "items": {"type": "string"}},
                "denied_tools": {"type": "array", "items": {"type": "string"}},
                "max_turns_per_hour": {"type": "integer", "minimum": 0},
                "max_concurrent_runs": {"type": "integer", "minimum": 0},
                "max_daily_runs": {"type": "integer", "minimum": 0},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_routine",
        "description": (
            "Schedule recurring work for a bot. trigger_kind is interval (needs "
            "interval_seconds) or once (needs run_at ISO timestamp)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 100},
                "bot_name": {"type": "string"},
                "prompt": {"type": "string"},
                "trigger_kind": {"type": "string", "enum": ["interval", "once"]},
                "interval_seconds": {"type": "integer", "minimum": 15},
                "run_at": {"type": "string"},
            },
            "required": ["name", "bot_name", "prompt", "trigger_kind"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_routine",
        "description": (
            "Change a routine: rename, re-prompt, pause (enabled=false), resume, or "
            "change its cadence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "routine_id": {"type": "string"},
                "name": {"type": "string"},
                "bot_name": {"type": "string"},
                "prompt": {"type": "string"},
                "trigger_kind": {"type": "string", "enum": ["interval", "once"]},
                "interval_seconds": {"type": "integer", "minimum": 15},
                "run_at": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["routine_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_routine",
        "description": "Remove a scheduled routine permanently.",
        "inputSchema": {
            "type": "object",
            "properties": {"routine_id": {"type": "string"}},
            "required": ["routine_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "bind_plugin",
        "description": (
            "Attach or update an MCP plugin binding on a bot. allow_tools/deny_tools "
            "are tool-name lists (['*'] allows every tool). enable=false to pause the "
            "binding without deleting it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "bot_name": {"type": "string"},
                "plugin_id": {"type": "string"},
                "enabled": {"type": "boolean", "default": True},
                "allow_tools": {"type": "array", "items": {"type": "string"}},
                "deny_tools": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["bot_name", "plugin_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "unbind_plugin",
        "description": "Detach an MCP plugin from a bot (the plugin itself is kept).",
        "inputSchema": {
            "type": "object",
            "properties": {"bot_name": {"type": "string"}, "plugin_id": {"type": "string"}},
            "required": ["bot_name", "plugin_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_engine_models",
        "description": "List the model ids an engine currently offers (use before create_bot or configure_bot).",
        "inputSchema": {
            "type": "object",
            "properties": {"engine": {"type": "string", "enum": ["kiro", "opencode", "codex"]}},
            "required": ["engine"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a short, non-interactive host command (no shell, argument list only, "
            "hard timeout) and return stdout/stderr. For inspecting the machine the "
            "operator asked about - never for destructive system changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 64},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fleet_audit",
        "description": "Recent governance audit entries: permission decisions, runs, policy changes.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
            "additionalProperties": False,
        },
    },
]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(add_help=False)
    root.add_argument("--caller", required=True)
    return root


def main() -> None:
    caller = parser().parse_args().caller.strip()
    base_url = _validated_base_url(os.environ.get("KYN_CONTROL_URL", "http://127.0.0.1:8765"))
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = _dispatch(message, base_url, caller)
        except Exception as exc:
            request_id = message.get("id") if isinstance(locals().get("message"), dict) else None
            response = _error(request_id, -32603, f"fleet tool failed: {type(exc).__name__}: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def _dispatch(message: Mapping[str, Any], base_url: str, caller: str) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = str(message.get("method") or "")
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "kyn-fleet", "version": "0.1.0"},
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method != "tools/call":
        return _error(request_id, -32601, "method not found")
    params = message.get("params") if isinstance(message.get("params"), Mapping) else {}
    name = str(params.get("name") or "")
    arguments = params.get("arguments") if isinstance(params.get("arguments"), Mapping) else {}
    try:
        value = _call_tool(base_url, caller, name, dict(arguments))
    except Exception as exc:
        return _result(request_id, {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True})
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return _result(request_id, {"content": [{"type": "text", "text": text}], "structuredContent": value, "isError": False})


def _authorize(base_url: str, caller: str, tool: str) -> None:
    """Enforce the hard delegation guardrail before a fleet admin tool runs."""
    try:
        verdict = _http(
            base_url, "POST", "/api/control/authorize", {"caller": caller, "tool": tool}
        )
    except Exception as exc:
        raise RuntimeError(f"delegation guardrail unreachable: {exc}") from exc
    if not isinstance(verdict, dict) or not verdict.get("allowed"):
        reason = str((verdict or {}).get("reason") or "delegation denied")
        raise RuntimeError(reason)


def _call_tool(base: str, caller: str, name: str, args: dict[str, Any]) -> Any:
    if name == "fleet_status":
        bots = _http(base, "GET", "/api/bots")
        runs = _runs_snapshot(base)
        interactions = _http(base, "GET", "/api/interactions?status=pending")
        return {"bots": bots, "runs": runs, "pending_approvals": interactions}
    if name == "create_bot":
        _authorize(base, caller, name)
        payload = {
            "name": _req(args, "name"),
            "cwd": _req(args, "cwd"),
            "engine": str(args.get("engine") or "kiro"),
            "model": str(args.get("model") or ""),
            "effort": str(args.get("effort") or ""),
            "agent": str(args.get("agent") or ""),
            "brief": str(args.get("brief") or ""),
        }
        return _http(base, "POST", "/api/bots", payload)
    if name == "configure_bot":
        bot_name = _quote(args, "name")
        changes: dict[str, Any] = {}
        for key in ("model", "effort", "agent", "cwd", "brief"):
            if key in args and args[key] is not None:
                changes[key] = str(args[key])
        if not changes:
            # Field-less call is a read — reads are never gated.
            return _http(base, "GET", f"/api/bots/{bot_name}")
        _authorize(base, caller, name)
        return _http(base, "PATCH", f"/api/bots/{bot_name}", changes)
    if name == "delete_bot":
        _authorize(base, caller, name)
        target = _quote(args, "name")
        return _http(base, "DELETE", f"/api/bots/{target}")
    if name == "set_bot_policy":
        _authorize(base, caller, name)
        bot_name = _quote(args, "name")
        current = _http(base, "GET", f"/api/bots/{bot_name}/policy")
        if isinstance(current, list):
            current = {}
        payload = {
            "approval_mode": str(args.get("approval_mode") or current.get("approval_mode") or "ask"),
            "allowed_tools": list(args.get("allowed_tools", current.get("allowed_tools") or [])),
            "denied_tools": list(args.get("denied_tools", current.get("denied_tools") or [])),
            "max_turns_per_hour": int(args.get("max_turns_per_hour", current.get("max_turns_per_hour") or 0)),
            "max_concurrent_runs": int(args.get("max_concurrent_runs", current.get("max_concurrent_runs") or 0)),
            "max_daily_runs": int(args.get("max_daily_runs", current.get("max_daily_runs") or 0)),
            "auto_failover": bool(current.get("auto_failover") or False),
            "failover_engines": list(current.get("failover_engines") or []),
        }
        return _http(base, "PUT", f"/api/bots/{bot_name}/policy", payload)
    if name == "create_routine":
        _authorize(base, caller, name)
        payload = {
            "name": _req(args, "name"),
            "bot_name": _req(args, "bot_name"),
            "prompt": _req(args, "prompt"),
            "trigger_kind": _req(args, "trigger_kind"),
            "enabled": True,
        }
        if "interval_seconds" in args and args["interval_seconds"] is not None:
            payload["interval_seconds"] = int(args["interval_seconds"])
        if args.get("run_at"):
            payload["run_at"] = str(args["run_at"])
        return _http(base, "POST", "/api/routines", payload)
    if name == "update_routine":
        _authorize(base, caller, name)
        routine_id = _quote(args, "routine_id")
        changes = {
            key: args[key]
            for key in ("name", "bot_name", "prompt", "trigger_kind", "interval_seconds", "run_at", "enabled")
            if key in args and args[key] is not None
        }
        if not changes:
            raise ValueError("pass at least one field to change")
        return _http(base, "PATCH", f"/api/routines/{routine_id}", changes)
    if name == "delete_routine":
        _authorize(base, caller, name)
        return _http(base, "DELETE", f"/api/routines/{_quote(args, 'routine_id')}")
    if name == "bind_plugin":
        _authorize(base, caller, name)
        payload = {
            "enabled": bool(args.get("enabled", True)),
            "allow_tools": list(args.get("allow_tools") or ["*"]),
            "deny_tools": list(args.get("deny_tools") or []),
        }
        bot_name = _quote(args, "bot_name")
        plugin_id = _quote(args, "plugin_id")
        return _http(base, "PUT", f"/api/bots/{bot_name}/plugins/{plugin_id}", payload)
    if name == "unbind_plugin":
        _authorize(base, caller, name)
        bot_name = _quote(args, "bot_name")
        plugin_id = _quote(args, "plugin_id")
        return _http(base, "DELETE", f"/api/bots/{bot_name}/plugins/{plugin_id}")
    if name == "list_engine_models":
        engine = _quote(args, "engine")
        return _http(base, "GET", f"/api/engines/{engine}/models")
    if name == "run_command":
        _authorize(base, caller, name)
        return _run_command(args)
    if name == "fleet_audit":
        limit = min(max(int(args.get("limit") or 20), 1), 100)
        return _http(base, "GET", f"/api/audit?limit={limit}")
    raise ValueError(f"unknown fleet tool {name!r}")


def _runs_snapshot(base: str) -> list[dict[str, Any]]:
    """Best-effort list of active runs; missing run APIs must not break status."""
    try:
        payload = _http(base, "GET", "/api/runs?limit=20")
    except Exception:
        return []
    if isinstance(payload, dict):
        payload = payload.get("runs") or payload.get("items") or []
    return [run for run in payload if isinstance(run, dict) and str(run.get("status", "")) in {"queued", "running"}]


def _run_command(args: dict[str, Any]) -> dict[str, Any]:
    command = args.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part.strip() for part in command):
        raise ValueError("command must be a non-empty list of argument strings")
    if len(command) > 64:
        raise ValueError("command has too many parts")
    timeout = min(max(int(args.get("timeout_seconds") or 30), 1), 120)
    cwd = str(args.get("cwd") or "").strip() or None
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - argument list, no shell
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"executable not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"command exceeded {timeout}s and was killed") from exc
    elapsed = round(time.monotonic() - started, 3)

    def _clip(raw: bytes) -> str:
        text = raw.decode("utf-8", "replace")
        if len(text) > MAX_OUTPUT_CHARS:
            return text[:MAX_OUTPUT_CHARS] + f"… (+{len(text) - MAX_OUTPUT_CHARS} chars)"
        return text

    return {
        "command": command,
        "exit_code": completed.returncode,
        "elapsed_seconds": elapsed,
        "stdout": _clip(completed.stdout),
        "stderr": _clip(completed.stderr),
    }


def _req(args: Mapping[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _quote(args: Mapping[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return urllib.parse.quote(value, safe="")


def _http(base: str, method: str, path: str, payload: Any | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:  # noqa: S310 - loopback URL validated
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"control plane returned HTTP {exc.code}: {detail}") from exc
    if not body:
        return {"ok": True}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def _validated_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("KYN_CONTROL_URL must be a loopback HTTP origin")
    host = parsed.hostname.rstrip(".").casefold()
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("control URL must be loopback")
        except ValueError as exc:
            raise ValueError("control URL must be loopback") from exc
    return value.rstrip("/")


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
