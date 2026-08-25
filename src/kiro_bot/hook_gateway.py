"""Narrow public relay for authenticated provider webhooks.

Run this beside the loopback-only control room and point a public HTTPS tunnel
at the relay port.  It deliberately exposes only /hooks/* and forwards only the
headers needed by the supported provider signature contracts.
"""

from __future__ import annotations

import asyncio
import http.client
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlencode

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, Response
except ImportError as exc:  # pragma: no cover - optional server dependency
    raise RuntimeError("the hooks gateway requires the server extra") from exc


_PROVIDERS = frozenset({"slack", "github", "whatsapp", "email", "webhook"})
_FORWARDED_HEADERS = frozenset(
    {
        "content-type",
        "x-slack-request-timestamp",
        "x-slack-signature",
        "x-hub-signature-256",
        "x-github-event",
        "x-github-delivery",
        "x-kiro-timestamp",
        "x-kiro-signature-256",
    }
)
_MAX_BODY = 1_000_000


class GatewayError(RuntimeError):
    pass


Forward = Callable[
    [str, str, bytes, Mapping[str, str]],
    Awaitable[tuple[int, bytes, str]],
]


def create_hook_gateway(
    *, upstream_host: str = "127.0.0.1", upstream_port: int = 8765, forward: Forward | None = None
) -> FastAPI:
    if upstream_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("hooks gateway upstream must be loopback")
    if not 1 <= int(upstream_port) <= 65535:
        raise ValueError("upstream port must be between 1 and 65535")
    relay = forward or _forwarder(upstream_host, int(upstream_port))
    app = FastAPI(title="Kiro Bot Hooks Gateway", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/hooks/{provider}/{binding_id}", methods=["GET", "POST"])
    async def hook(provider: str, binding_id: str, request: Request) -> Response:
        if provider not in _PROVIDERS:
            return JSONResponse(status_code=404, content={"error": "hook_not_found"})
        if not binding_id or len(binding_id) > 80:
            return JSONResponse(status_code=404, content={"error": "hook_not_found"})
        body = await request.body()
        if len(body) > _MAX_BODY:
            return JSONResponse(status_code=413, content={"error": "payload_too_large"})
        query = urlencode(list(request.query_params.multi_items()))
        path = f"/hooks/{provider}/{binding_id}"
        if query:
            path += "?" + query
        headers = {
            key.lower(): value
            for key, value in request.headers.items()
            if key.lower() in _FORWARDED_HEADERS
        }
        try:
            status, response_body, content_type = await relay(
                request.method, path, body, headers
            )
        except GatewayError:
            return JSONResponse(status_code=502, content={"error": "control_plane_unavailable"})
        return Response(content=response_body, status_code=status, media_type=content_type)

    return app


def _forwarder(host: str, port: int) -> Forward:
    async def forward(
        method: str, path: str, body: bytes, headers: Mapping[str, str]
    ) -> tuple[int, bytes, str]:
        return await asyncio.to_thread(_forward_sync, host, port, method, path, body, headers)

    return forward


def _forward_sync(
    host: str,
    port: int,
    method: str,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
) -> tuple[int, bytes, str]:
    connection = http.client.HTTPConnection(host, port, timeout=15)
    try:
        connection.request(method, path, body=body, headers=dict(headers))
        response = connection.getresponse()
        payload = response.read(_MAX_BODY + 1)
        if len(payload) > _MAX_BODY:
            raise GatewayError("upstream response is too large")
        content_type = response.getheader("content-type", "application/json").split(";", 1)[0]
        return response.status, payload, content_type
    except (OSError, http.client.HTTPException) as exc:
        raise GatewayError("control plane is unavailable") from exc
    finally:
        connection.close()
