from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi.testclient import TestClient

from kiro_bot.hook_gateway import create_hook_gateway


def test_gateway_exposes_only_hooks_and_forwards_signature_contract() -> None:
    calls: list[tuple[str, str, bytes, Mapping[str, str]]] = []

    async def forward(
        method: str, path: str, body: bytes, headers: Mapping[str, str]
    ) -> tuple[int, bytes, str]:
        calls.append((method, path, body, headers))
        return 200, b"challenge", "text/plain"

    app = create_hook_gateway(forward=forward)
    with TestClient(app) as client:
        assert client.get("/api/bots").status_code == 404
        assert client.get("/app/").status_code == 404
        response = client.get(
            "/hooks/whatsapp/personal-whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify",
                "hub.challenge": "123",
            },
            headers={"authorization": "must-not-forward"},
        )
    assert response.status_code == 200 and response.text == "challenge"
    assert calls == [
        (
            "GET",
            "/hooks/whatsapp/personal-whatsapp?hub.mode=subscribe&hub.verify_token=verify&hub.challenge=123",
            b"",
            {},
        )
    ]


def test_gateway_rejects_unknown_providers_and_large_payloads() -> None:
    async def unused(*_args: Any) -> tuple[int, bytes, str]:
        raise AssertionError("must not forward")

    app = create_hook_gateway(forward=unused)
    with TestClient(app) as client:
        assert client.post("/hooks/unknown/value", content=b"{}").status_code == 404
        assert client.post(
            "/hooks/whatsapp/value", content=b"x" * 1_000_001
        ).status_code == 413
