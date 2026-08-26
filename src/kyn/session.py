from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from .protocol import (
    Event,
    REQUEST_PERMISSION,
    SESSION_CANCEL,
    SESSION_PROMPT,
    SESSION_SET_MODE,
    SESSION_SET_MODEL,
    SESSION_UPDATE,
    choose_permission_option,
    choose_reject_option,
    parse_permission,
    parse_update,
    text_prompt,
)
from .runtime import AcpError, AcpProcessDied, AcpRuntime


class AcpSession:
    def __init__(
        self,
        runtime: AcpRuntime,
        session_id: str,
        queue: asyncio.Queue[dict[str, Any] | None],
        config: dict[str, Any],
    ) -> None:
        self.runtime = runtime
        self.session_id = session_id
        self.queue = queue
        self.config = config
        self._turn_lock = asyncio.Lock()
        self._permission_options: dict[str | int, list[dict[str, Any]]] = {}
        self._tool_identities: dict[str, tuple[str, str]] = {}
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    async def set_mode(self, mode: str) -> None:
        await self.runtime.request(
            SESSION_SET_MODE, {"sessionId": self.session_id, "modeId": mode}, 30
        )

    async def set_model(self, model: str) -> None:
        await self.runtime.request(
            SESSION_SET_MODEL, {"sessionId": self.session_id, "modelId": model}, 30
        )

    async def prompt(self, message: str, timeout: float = 7200) -> AsyncIterator[Event]:
        if self._turn_lock.locked():
            raise AcpError("only one prompt may run on a Kiro session at a time")
        async with self._turn_lock:
            self._active = True
            self._tool_identities.clear()
            request_id = await self.runtime.routed_request(
                SESSION_PROMPT,
                {"sessionId": self.session_id, "prompt": text_prompt(message)},
                self.session_id,
            )
            try:
                while True:
                    try:
                        frame = await asyncio.wait_for(self.queue.get(), timeout=timeout)
                    except asyncio.TimeoutError as exc:
                        await self.cancel()
                        raise AcpError(f"Kiro turn exceeded {timeout:.0f} seconds") from exc
                    if frame is None:
                        raise AcpProcessDied("Kiro ACP runtime ended during the turn")
                    if _is_response_for(frame, request_id):
                        if "error" in frame:
                            raise AcpError(str(frame["error"]))
                        result = frame.get("result") if isinstance(frame.get("result"), dict) else {}
                        yield Event(
                            kind="complete",
                            stop_reason=str(result.get("stopReason") or ""),
                            raw=frame,
                        )
                        return
                    method = frame.get("method")
                    if method == SESSION_UPDATE:
                        for event in parse_update(frame):
                            if event.tool_call_id and (event.tool_name or event.mcp_server_name):
                                self._tool_identities[event.tool_call_id] = (
                                    event.tool_name,
                                    event.mcp_server_name,
                                )
                            yield event
                    elif method == REQUEST_PERMISSION and frame.get("id") is not None:
                        event = parse_permission(frame)
                        identity = self._tool_identities.get(event.tool_call_id)
                        if identity is not None:
                            event.tool_name, event.mcp_server_name = identity
                        self._permission_options[event.request_id] = event.options
                        yield event
                    else:
                        yield Event(kind="protocol", raw=frame)
            finally:
                self._active = False

    async def approve(self, request_id: str | int, *, always: bool = False) -> None:
        options = self._permission_options.pop(request_id, [])
        option_id = choose_permission_option(options, always=always)
        if not option_id:
            option_id = "allow_always" if always else "allow_once"
        await self.runtime.respond(
            request_id,
            {"outcome": {"outcome": "selected", "optionId": option_id}},
        )

    async def reject(self, request_id: str | int) -> None:
        options = self._permission_options.pop(request_id, [])
        option_id = choose_reject_option(options)
        outcome = (
            {"outcome": "selected", "optionId": option_id}
            if option_id
            else {"outcome": "cancelled"}
        )
        await self.runtime.respond(request_id, {"outcome": outcome})

    async def cancel(self) -> None:
        await self.runtime.notify(SESSION_CANCEL, {"sessionId": self.session_id})


def _is_response_for(frame: dict[str, Any], request_id: int) -> bool:
    try:
        return int(frame.get("id")) == request_id and ("result" in frame or "error" in frame)
    except (TypeError, ValueError, OverflowError):
        return False
