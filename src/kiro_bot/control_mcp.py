from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping


PROTOCOL_VERSION = "2025-06-18"


TOOLS = [
    {
        "name": "list_bots",
        "description": "List durable named KYNs available for team plans and delegation.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_team_plans",
        "description": "List durable multi-bot team plans and their current states.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_team_plan",
        "description": "Inspect a team plan, its nodes, dependencies, and aggregated results.",
        "inputSchema": {
            "type": "object",
            "properties": {"plan_id": {"type": "string"}},
            "required": ["plan_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_team_plan",
        "description": "Create and optionally start a durable dependency DAG across named bots.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "nodes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "bot_name": {"type": "string"},
                            "prompt": {"type": "string"},
                        },
                        "required": ["id", "bot_name", "prompt"],
                        "additionalProperties": False,
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"source": {"type": "string"}, "target": {"type": "string"}},
                        "required": ["source", "target"],
                        "additionalProperties": False,
                    },
                    "default": [],
                },
                "start": {"type": "boolean", "default": True},
                "max_fanout": {"type": "integer", "minimum": 1, "maximum": 32, "default": 4},
                "max_depth": {"type": "integer", "minimum": 0, "maximum": 32, "default": 4},
            },
            "required": ["name", "nodes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "start_team_plan",
        "description": "Start a paused durable team plan.",
        "inputSchema": {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"], "additionalProperties": False},
    },
    {
        "name": "cancel_team_plan",
        "description": "Cancel a running or pending team plan and its active child runs.",
        "inputSchema": {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"], "additionalProperties": False},
    },
    {
        "name": "call_bot",
        "description": "Ask another durable named bot to do focused work and wait for its result. Never target the calling bot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bot_name": {"type": "string"},
                "message": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600, "default": 300},
            },
            "required": ["bot_name", "message"],
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
    base_url = _validated_base_url(os.environ.get("KIRO_BOT_CONTROL_URL", "http://127.0.0.1:8765"))
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = _dispatch(message, base_url, caller)
        except Exception as exc:
            request_id = message.get("id") if isinstance(locals().get("message"), dict) else None
            response = _error(request_id, -32603, f"control tool failed: {type(exc).__name__}: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def _dispatch(message: Mapping[str, Any], base_url: str, caller: str) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = str(message.get("method") or "")
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _result(request_id, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": {"name": "kiro-bot-control", "version": "0.1.0"}})
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


def _call_tool(base: str, caller: str, name: str, args: dict[str, Any]) -> Any:
    if name == "list_bots":
        return _http(base, "GET", "/api/bots")
    if name == "list_team_plans":
        return _http(base, "GET", "/api/delegations")
    if name == "get_team_plan":
        return _http(base, "GET", f"/api/delegations/{_quote(args, 'plan_id')}")
    if name == "create_team_plan":
        return _http(base, "POST", "/api/delegations", args)
    if name == "start_team_plan":
        return _http(base, "POST", f"/api/delegations/{_quote(args, 'plan_id')}/start", {})
    if name == "cancel_team_plan":
        return _http(base, "POST", f"/api/delegations/{_quote(args, 'plan_id')}/cancel", {})
    if name == "call_bot":
        target = str(args.get("bot_name") or "").strip()
        message = str(args.get("message") or "").strip()
        if not target or not message:
            raise ValueError("bot_name and message are required")
        if target == caller:
            raise ValueError("a bot cannot synchronously call itself")
        created = _http(base, "POST", f"/api/bots/{urllib.parse.quote(target, safe='')}/turns", {"message": message})
        run_id = str(created.get("run_id") or "")
        if not run_id:
            raise RuntimeError("the control plane returned no run id")
        deadline = time.monotonic() + min(max(int(args.get("timeout_seconds", 300)), 1), 600)
        while time.monotonic() < deadline:
            run = _http(base, "GET", f"/api/runs/{urllib.parse.quote(run_id, safe='')}")
            if str(run.get("status")) in {"complete", "failed", "cancelled"}:
                return run
            time.sleep(0.25)
        raise TimeoutError(f"bot call {run_id} did not finish before the timeout")
    raise ValueError(f"unknown control tool {name!r}")


def _http(base: str, method: str, path: str, payload: Any | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - loopback URL validated
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"control plane returned HTTP {exc.code}: {detail}") from exc


def _validated_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise ValueError("KIRO_BOT_CONTROL_URL must be a loopback HTTP origin")
    host = parsed.hostname.rstrip(".").casefold()
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("control URL must be loopback")
        except ValueError as exc:
            raise ValueError("control URL must be loopback") from exc
    return value.rstrip("/")


def _quote(args: Mapping[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return urllib.parse.quote(value, safe="")


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
