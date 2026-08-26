from __future__ import annotations

import asyncio
import json
import os
import signal
import shutil
import sys
from collections import deque
from pathlib import Path
from typing import Any

from .protocol import (
    INITIALIZE,
    PROTOCOL_VERSION,
    REQUEST_PERMISSION,
    SESSION_LOAD,
    SESSION_NEW,
    SESSION_TERMINATE,
    SESSION_UPDATE,
    session_new_params,
)


class AcpError(RuntimeError):
    pass


class AcpProcessDied(AcpError):
    pass


_TRACE_REDACTED = "<redacted>"
_TRACE_SECRET_KEYS = (
    "token",
    "secret",
    "password",
    "passwd",
    "auth",
    "authorization",
    "cookie",
    "credential",
    "apikey",
    "accesskey",
    "privatekey",
)
_TRACE_SECRET_CONTAINERS = frozenset(
    {"env", "environment", "headers", "header", "secrets", "credentials"}
)


class AcpRuntime:
    """One Kiro ACP process with a single stdout reader and session demux."""

    def __init__(
        self,
        cwd: str | Path,
        *,
        agent: str = "",
        model: str = "",
        effort: str = "",
        command: list[str] | None = None,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.agent = agent
        self.model = model
        self.effort = effort
        self.command = command
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._routed: dict[int, str] = {}
        self._queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        self._write_lock = asyncio.Lock()
        self._dead_reason = ""
        self.stderr_tail: deque[str] = deque(maxlen=100)
        self.capabilities: dict[str, Any] = {}

    @property
    def alive(self) -> bool:
        return bool(self.process and self.process.returncode is None and not self._dead_reason)

    async def start(self) -> None:
        if self.process is not None:
            raise AcpError("runtime already started")
        self.cwd.mkdir(parents=True, exist_ok=True)
        argv = self.command or self._kiro_command()
        self.process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.cwd),
            start_new_session=os.name == "posix",
            # Kiro can emit a single large tool/command discovery frame during
            # session load. The asyncio default (64 KiB) is too small and would
            # kill the one reader responsible for every logical session.
            limit=16 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._reader_loop(), name="kiro-acp-reader")
        self._stderr_task = asyncio.create_task(self._stderr_loop(), name="kiro-acp-stderr")
        result = await self.request(
            INITIALIZE,
            {
                "clientInfo": {"name": "kyn", "version": "0.1.0"},
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
            timeout=30,
        )
        self.capabilities = result.get("agentCapabilities", {}) if isinstance(result, dict) else {}

    def _kiro_command(self) -> list[str]:
        binary = shutil.which("kiro-cli")
        if not binary:
            raise AcpError("kiro-cli is not installed or is not in PATH")
        argv = [binary, "acp"]
        if self.agent:
            argv.extend(["--agent", self.agent])
        if self.model:
            argv.extend(["--model", self.model])
        if self.effort:
            argv.extend(["--effort", self.effort])
        return argv

    async def request(self, method: str, params: dict[str, Any], timeout: float = 30) -> dict:
        request_id = self._allocate_id()
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    async def routed_request(self, method: str, params: dict[str, Any], session_id: str) -> int:
        if session_id not in self._queues:
            raise AcpError(f"session {session_id!r} is not registered")
        request_id = self._allocate_id()
        self._routed[request_id] = session_id
        try:
            await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        except BaseException:
            self._routed.pop(request_id, None)
            raise
        return request_id

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def respond(self, request_id: str | int, result: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def create_session(self, mcp_servers: list[dict[str, Any]] | None = None) -> "AcpSession":
        from .session import AcpSession

        response = await self.request(SESSION_NEW, session_new_params(str(self.cwd), mcp_servers), 120)
        session_id = str(response.get("sessionId") or "")
        if not session_id:
            raise AcpError(f"session/new returned no sessionId: {response}")
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._queues[session_id] = queue
        return AcpSession(self, session_id, queue, response)

    async def load_session(
        self,
        session_id: str,
        *,
        transcript_path: str = "",
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> "AcpSession":
        from .session import AcpSession

        if not self.capabilities.get("loadSession", False):
            raise AcpError("Kiro did not advertise session/load support")
        params = {
            "sessionId": session_id,
            "cwd": str(self.cwd),
            "mcpServers": mcp_servers or [],
        }
        if transcript_path:
            params["_meta"] = {"_kiro.dev/session_file": transcript_path}
        response = await self.request(SESSION_LOAD, params, 120)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._queues[session_id] = queue
        return AcpSession(self, session_id, queue, response)

    async def terminate_session(self, session_id: str) -> None:
        try:
            await self.request(SESSION_TERMINATE, {"sessionId": session_id}, 10)
        finally:
            self.unregister(session_id)

    def unregister(self, session_id: str) -> None:
        self._queues.pop(session_id, None)
        for request_id, routed_session in list(self._routed.items()):
            if routed_session == session_id:
                self._routed.pop(request_id, None)

    async def close(self) -> None:
        process = self.process
        if process is None:
            return
        if process.returncode is None:
            self._signal_process_tree(process, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._signal_process_tree(process, signal.SIGKILL)
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._stderr_task) if task),
            return_exceptions=True,
        )
        self.process = None

    @staticmethod
    def _signal_process_tree(process: asyncio.subprocess.Process, sig: signal.Signals) -> None:
        """Signal Kiro and every MCP/tool descendant in its process group."""
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass

    async def _write(self, message: dict[str, Any]) -> None:
        if not self.alive or not self.process or not self.process.stdin:
            raise AcpProcessDied(self._dead_reason or "Kiro ACP process is not running")
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode()
        self._trace("->", message)
        async with self._write_lock:
            try:
                self.process.stdin.write(encoded)
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                self._mark_dead(f"stdin failed: {exc}")
                raise AcpProcessDied(self._dead_reason) from exc

    async def _reader_loop(self) -> None:
        assert self.process and self.process.stdout
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    self._mark_dead(f"Kiro exited with code {self.process.returncode}")
                    return
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not isinstance(message, dict):
                    continue
                self._trace("<-", message)
                await self._route(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._mark_dead(f"reader failed: {exc}")

    async def _route(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        is_response = request_id is not None and ("result" in message or "error" in message)
        if is_response:
            numeric_id = _numeric_id(request_id)
            if numeric_id is None:
                return
            future = self._pending.get(numeric_id)
            if future and not future.done():
                if "error" in message:
                    future.set_exception(AcpError(_rpc_error(message["error"])))
                else:
                    result = message.get("result")
                    future.set_result(result if isinstance(result, dict) else {})
                return
            session_id = self._routed.pop(numeric_id, None)
            if session_id and session_id in self._queues:
                await self._queues[session_id].put(message)
            return

        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        session_id = str(params.get("sessionId") or "")
        if session_id and session_id in self._queues:
            await self._queues[session_id].put(message)
            return

        if request_id is not None and message.get("method") == REQUEST_PERMISSION:
            # A request with no visible owner must be answered fail-closed. If it
            # is dropped, Kiro can remain blocked forever waiting for the client.
            await self.respond(request_id, {"outcome": {"outcome": "cancelled"}})
            return

        if not session_id:
            for queue in list(self._queues.values()):
                await queue.put(message)

    async def _stderr_loop(self) -> None:
        assert self.process and self.process.stderr
        try:
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    return
                self.stderr_tail.append(line.decode(errors="replace").rstrip())
        except asyncio.CancelledError:
            raise

    def _allocate_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _mark_dead(self, reason: str) -> None:
        if self._dead_reason:
            return
        self._dead_reason = reason
        error = AcpProcessDied(reason)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        for queue in self._queues.values():
            queue.put_nowait(None)

    @staticmethod
    def _trace(direction: str, message: dict[str, Any]) -> None:
        if os.environ.get("KYN_TRACE") == "1":
            print(
                f"ACP {direction} {json.dumps(_redact_trace(message), ensure_ascii=False)}",
                file=sys.stderr,
                flush=True,
            )


def _numeric_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _redact_trace(value: Any, *, secret_container: bool = False) -> Any:
    """Return a recursively redacted copy suitable only for diagnostic trace.

    MCP environment and header containers commonly encode their secret under a
    generic ``value`` key, so their values are redacted by container context in
    addition to ordinary secret-bearing key names.
    """
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        is_named_pair = secret_container and any(
            str(candidate).casefold() == "value" for candidate in value
        )
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = "".join(character for character in key.casefold() if character.isalnum())
            if secret_container:
                # Preserve the public name of an env/header pair so traces can
                # still diagnose which setting was present, never its value.
                if is_named_pair and normalized in {"name", "key"} and isinstance(item, str):
                    redacted[key] = item
                else:
                    redacted[key] = _redact_trace(item, secret_container=True)
                continue
            if any(marker in normalized for marker in _TRACE_SECRET_KEYS):
                redacted[key] = _TRACE_REDACTED
            elif normalized in _TRACE_SECRET_CONTAINERS:
                redacted[key] = _redact_trace(item, secret_container=True)
            else:
                redacted[key] = _redact_trace(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact_trace(item, secret_container=secret_container) for item in value]
    if secret_container and value is not None:
        return _TRACE_REDACTED
    return value


def _rpc_error(error: Any) -> str:
    if isinstance(error, dict):
        message = str(error.get("message") or "ACP request failed")
        data = error.get("data")
        return f"{message}: {data}" if data else message
    return str(error)
