from __future__ import annotations

import os

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")
from fastapi.testclient import TestClient

from kyn.remote import access_token, token_authorized
from kyn.server import create_app
from kyn.store import Store


class FakeEngine:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def submit(self, bot_name: str, message: str) -> str:
        return "run-1"

    async def get_run(self, run_id: str) -> None:
        return None

    async def subscribe(self, run_id: str, after: int = 0):
        yield {"kind": "text", "text": "ok"}

    async def decide_permission(self, run_id: str, request_id: str, decision: str) -> None:
        return None

    async def cancel(self, run_id: str) -> None:
        return None


def test_token_authorized_uses_hmac_compare() -> None:
    assert token_authorized("secret", "secret")
    assert not token_authorized("wrong", "secret")
    assert not token_authorized(None, "secret")


def test_access_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KYN_ACCESS_TOKEN", "abc")
    assert access_token() == "abc"
    monkeypatch.delenv("KYN_ACCESS_TOKEN")
    assert access_token() is None


def test_remote_guard_blocks_api_without_token(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KYN_ACCESS_TOKEN", "test-token")
    app = create_app(Store(tmp_path / "store"), FakeEngine())
    client = TestClient(app)
    denied = client.get("/api/bots")
    assert denied.status_code == 401
    allowed = client.get("/api/bots", headers={"Authorization": "Bearer test-token"})
    assert allowed.status_code == 200
    health = client.get("/api/health")
    assert health.status_code == 200
