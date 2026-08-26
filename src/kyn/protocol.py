from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "2025-08-22"

INITIALIZE = "initialize"
SESSION_NEW = "session/new"
SESSION_LOAD = "session/load"
SESSION_PROMPT = "session/prompt"
SESSION_CANCEL = "session/cancel"
SESSION_SET_MODE = "session/set_mode"
SESSION_SET_MODEL = "session/set_model"
SESSION_UPDATE = "session/update"
REQUEST_PERMISSION = "session/request_permission"
SESSION_TERMINATE = "_kiro.dev/session/terminate"


@dataclass(slots=True)
class Event:
    kind: str
    text: str = ""
    title: str = ""
    tool_call_id: str = ""
    request_id: str | int = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    # Canonical identities from Kiro's trusted `_meta.kiro` channel. Titles are
    # model-authored display prose and must never drive allow-list decisions.
    tool_name: str = ""
    mcp_server_name: str = ""
    interaction_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def text_prompt(message: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": message}]


def session_new_params(cwd: str, mcp_servers: list[dict[str, Any]] | None = None) -> dict:
    return {"cwd": cwd, "mcpServers": mcp_servers or []}


def parse_update(message: dict[str, Any]) -> list[Event]:
    params = message.get("params")
    if not isinstance(params, dict):
        return [Event(kind="raw", raw=message)]
    update = params.get("update")
    if not isinstance(update, dict):
        return [Event(kind="raw", raw=message)]

    kind = str(update.get("sessionUpdate") or "")
    content = update.get("content")
    text = _content_text(content)

    if kind == "agent_message_chunk":
        return [Event(kind="text", text=text, raw=message)]
    if kind == "agent_thought_chunk":
        return [Event(kind="thinking", text=text, raw=message)]
    if kind == "user_message_chunk":
        return [Event(kind="user_echo", text=text, raw=message)]
    if kind in {"tool_call", "tool_call_update"}:
        tool_id = str(update.get("toolCallId") or update.get("tool_call_id") or "")
        title = str(update.get("title") or update.get("name") or "")
        status = str(update.get("status") or "")
        meta = update.get("_meta") if isinstance(update.get("_meta"), dict) else {}
        kiro_meta = meta.get("kiro") if isinstance(meta.get("kiro"), dict) else {}
        return [
            Event(
                kind="tool_update" if kind.endswith("update") else "tool_call",
                text=status,
                title=title,
                tool_call_id=tool_id,
                tool_name=str(kiro_meta.get("toolName") or ""),
                mcp_server_name=str(kiro_meta.get("mcpServerName") or ""),
                raw=message,
            )
        ]
    if kind == "usage_update":
        return [Event(kind="usage", raw=message)]
    if kind:
        return [Event(kind=kind, text=text, raw=message)]
    return [Event(kind="raw", raw=message)]


def parse_permission(message: dict[str, Any]) -> Event:
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    tool_call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
    options = params.get("options") if isinstance(params.get("options"), list) else []
    meta = tool_call.get("_meta") if isinstance(tool_call.get("_meta"), dict) else {}
    if not meta and isinstance(params.get("_meta"), dict):
        meta = params["_meta"]
    kiro_meta = meta.get("kiro") if isinstance(meta.get("kiro"), dict) else {}
    return Event(
        kind="permission",
        title=str(tool_call.get("title") or tool_call.get("name") or "Tool request"),
        tool_call_id=str(tool_call.get("toolCallId") or tool_call.get("id") or ""),
        request_id=message.get("id", ""),
        options=[o for o in options if isinstance(o, dict)],
        tool_name=str(kiro_meta.get("toolName") or ""),
        mcp_server_name=str(kiro_meta.get("mcpServerName") or ""),
        raw=message,
    )


def choose_permission_option(options: list[dict[str, Any]], always: bool = False) -> str | None:
    preferred_behaviours = ("allow_always", "allow_once") if always else ("allow_once", "allow")
    for preferred in preferred_behaviours:
        for option in options:
            option_id = str(option.get("optionId") or option.get("id") or "")
            if preferred in option_id.lower():
                return option_id
    for option in options:
        kind = str(option.get("kind") or option.get("name") or "").lower()
        if "allow" in kind and (always or "always" not in kind):
            return str(option.get("optionId") or option.get("id") or "") or None
    return None


def choose_reject_option(options: list[dict[str, Any]]) -> str | None:
    for option in options:
        searchable = " ".join(str(option.get(k, "")) for k in ("optionId", "id", "kind", "name"))
        if any(word in searchable.lower() for word in ("reject", "deny")):
            return str(option.get("optionId") or option.get("id") or "") or None
    return None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        value = content.get("text")
        return value if isinstance(value, str) else ""
    return ""
