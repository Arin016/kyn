"""Remote deployment helpers: optional bearer auth and CORS."""

from __future__ import annotations

import hmac
import os
from typing import Any

try:
    from fastapi import Request, WebSocket
    from fastapi.responses import JSONResponse
    from starlette.middleware.cors import CORSMiddleware
except ImportError:  # pragma: no cover - optional server extra
    Request = Any  # type: ignore[misc,assignment]
    WebSocket = Any  # type: ignore[misc,assignment]
    JSONResponse = Any  # type: ignore[misc,assignment]
    CORSMiddleware = None  # type: ignore[misc,assignment]

_PUBLIC_API_PATHS = frozenset({"/api/health"})


def access_token() -> str | None:
    raw = os.environ.get("KYN_ACCESS_TOKEN", "").strip()
    return raw or None


def allowed_origins() -> list[str]:
    raw = os.environ.get("KYN_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _extract_bearer(header_value: str | None) -> str | None:
    if not header_value:
        return None
    prefix = "bearer "
    if header_value.lower().startswith(prefix):
        return header_value[len(prefix):].strip() or None
    return None


def extract_access_token(request: Request) -> str | None:
    query = request.query_params.get("token")
    if query:
        return query
    return _extract_bearer(request.headers.get("authorization"))


def extract_websocket_token(websocket: WebSocket) -> str | None:
    query = websocket.query_params.get("token")
    if query:
        return query
    return _extract_bearer(websocket.headers.get("authorization"))


def token_authorized(supplied: str | None, expected: str) -> bool:
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def install_remote_guard(app: Any) -> None:
    """Attach CORS and optional bearer auth when env vars are set."""
    origins = allowed_origins()
    if origins and CORSMiddleware is not None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    expected = access_token()
    if not expected:
        return

    @app.middleware("http")
    async def require_access_token(request: Request, call_next: Any) -> Any:
        path = request.url.path
        if path.startswith("/app/") or path.startswith("/hooks/"):
            return await call_next(request)
        if path in _PUBLIC_API_PATHS:
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)
        supplied = extract_access_token(request)
        if not token_authorized(supplied, expected):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        return await call_next(request)


async def authorize_websocket(websocket: WebSocket) -> bool:
    expected = access_token()
    if not expected:
        return True
    supplied = extract_websocket_token(websocket)
    if token_authorized(supplied, expected):
        return True
    await websocket.close(code=4401, reason="unauthorized")
    return False
