from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import time
from typing import Any, AsyncIterator

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from kiro_bot.server import create_app
from kiro_bot.store import Store


@dataclass
class FakeRun:
    run_id: str
    bot_name: str
    status: str = "queued"


class FakeEngine:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.runs: dict[str, FakeRun] = {}
        self.decisions: list[tuple[str, str, str]] = []
        self.cancelled: list[str] = []

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def submit(self, bot_name: str, message: str) -> str:
        run_id = f"run-{len(self.runs) + 1}"
        self.runs[run_id] = FakeRun(run_id, bot_name)
        return run_id

    async def get_run(self, run_id: str) -> FakeRun | None:
        return self.runs.get(run_id)

    async def subscribe(self, run_id: str, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        events = [
            {"sequence": 1, "type": "text", "text": "hello"},
            {"sequence": 2, "type": "complete"},
        ]
        for event in events:
            if event["sequence"] > after:
                yield event
        self.runs[run_id].status = "complete"

    async def decide_permission(self, run_id: str, request_id: str, decision: str) -> bool:
        self.decisions.append((run_id, request_id, decision))
        return True

    async def cancel(self, run_id: str) -> bool:
        self.cancelled.append(run_id)
        self.runs[run_id].status = "cancelled"
        return True


class FakeCodingController:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.submissions: list[tuple[Any, str]] = []
        self.snapshot = {
            "id": "coding-1",
            "status": "awaiting_handoff",
            "version": 4,
        }

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def submit(self, spec: Any, *, idempotency_key: str) -> dict[str, Any]:
        self.submissions.append((spec, idempotency_key))
        return {"id": "coding-1", "status": "queued", "version": 1}

    async def list(self) -> list[dict[str, Any]]:
        return [dict(self.snapshot)]

    async def get(self, execution_id: str) -> dict[str, Any]:
        assert execution_id == "coding-1"
        return dict(self.snapshot)

    async def approve(self, execution_id: str, expected_version: int) -> dict[str, Any]:
        assert execution_id == "coding-1" and expected_version == 4
        return {**self.snapshot, "status": "ready", "version": 5}

    async def cancel(self, execution_id: str) -> dict[str, Any]:
        assert execution_id == "coding-1"
        return {**self.snapshot, "status": "cancelled", "version": 5}

def _test_client(app: Any) -> Any:
    try:
        from fastapi.testclient import TestClient

        return TestClient(app)
    except TypeError as exc:  # Starlette/httpx version mismatches occur in older environments.
        pytest.skip(f"FastAPI TestClient is incompatible with installed httpx: {exc}")


def test_bot_run_and_control_routes(tmp_path: Path) -> None:
    engine = FakeEngine()
    app = create_app(Store(tmp_path / "store"), engine)
    with _test_client(app) as client:
        assert engine.started
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        created = client.post("/api/bots", json={"name": "builder", "cwd": str(tmp_path)})
        assert created.status_code == 201
        assert created.json()["name"] == "builder"
        assert client.get("/api/bots/builder").status_code == 200

        submitted = client.post("/api/bots/builder/turns", json={"message": "Build it"})
        assert submitted.status_code == 202
        run_id = submitted.json()["run_id"]
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "queued"

        permission = client.post(
            f"/api/runs/{run_id}/permissions/request-1", json={"decision": "once"}
        )
        assert permission.status_code == 200
        assert engine.decisions == [(run_id, "request-1", "once")]

        invalid_permission = client.post(
            f"/api/runs/{run_id}/permissions/request-2", json={"decision": "allow_once"}
        )
        assert invalid_permission.status_code == 422
        persistent_permission = client.post(
            f"/api/runs/{run_id}/permissions/request-2", json={"decision": "always"}
        )
        assert persistent_permission.status_code == 422

        cancelled = client.post(f"/api/runs/{run_id}/cancel")
        assert cancelled.status_code == 200
        assert engine.cancelled == [run_id]
    assert engine.closed


def test_websocket_resume_and_terminal_marker(tmp_path: Path) -> None:
    engine = FakeEngine()
    engine.runs["run-1"] = FakeRun("run-1", "builder")
    app = create_app(Store(tmp_path / "store"), engine)
    with _test_client(app) as client:
        with client.websocket_connect("/ws/runs/run-1?after=1") as websocket:
            assert websocket.receive_json() == {"sequence": 2, "type": "complete"}
            terminal = websocket.receive_json()
            assert terminal["type"] == "terminal"
            assert terminal["run"]["status"] == "complete"


def test_live_socket_publishes_inbound_channel_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "live-secret"
    monkeypatch.setenv("KIRO_LIVE_SIGNING_SECRET", secret)
    app = create_app(Store(tmp_path / "store"), FakeEngine())
    with _test_client(app) as client:
        assert client.post(
            "/api/bots", json={"name": "builder", "cwd": str(tmp_path)}
        ).status_code == 201
        created = client.post(
            "/api/channels",
            json={
                "id": "phone",
                "name": "Phone",
                "kind": "webhook",
                "bot_name": "builder",
                "signing_secret_env": "KIRO_LIVE_SIGNING_SECRET",
                "trigger_prefix": "",
            },
        )
        assert created.status_code == 201
        stamp = str(int(time.time()))
        raw = json.dumps(
            {
                "delivery_id": "live-1",
                "thread_id": "phone-thread",
                "sender": "arin",
                "text": "from the phone",
            },
            separators=(",", ":"),
        ).encode()
        signature = "sha256=" + hmac.new(
            secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        with client.websocket_connect("/ws/live") as websocket:
            assert websocket.receive_json()["type"] == "hello"
            posted = client.post(
                "/hooks/webhook/phone",
                content=raw,
                headers={
                    "content-type": "application/json",
                    "x-kiro-timestamp": stamp,
                    "x-kiro-signature-256": signature,
                },
            )
            assert posted.status_code == 200
            payload = websocket.receive_json()
            assert payload["type"] == "channel_event"
            assert payload["bot_name"] == "builder"
            assert payload["event"]["text"] == "from the phone"
            assert payload["channel"]["id"] == "phone"


def test_validation_not_found_and_history(tmp_path: Path) -> None:
    engine = FakeEngine()
    store = Store(tmp_path / "store")
    app = create_app(store, engine)
    with _test_client(app) as client:
        relative = client.post("/api/bots", json={"name": "builder", "cwd": "relative"})
        assert relative.status_code == 422
        traversal = client.post("/api/bots", json={"name": "../builder", "cwd": str(tmp_path)})
        assert traversal.status_code == 422
        assert client.get("/api/bots/missing").status_code == 404
        assert client.get("/api/runs/missing").status_code == 404

        client.post("/api/bots", json={"name": "builder", "cwd": str(tmp_path)})
        history = client.get("/api/bots/builder/history")
        assert history.status_code == 200
        assert history.json() == {"bot": "builder", "turns": []}
        app.state.memory.record(
            "builder", "local", "api", "Remember this", "Remembered", event_id="m1"
        )
        memory = client.get("/api/bots/builder/memory")
        assert memory.status_code == 200
        assert memory.json()["events"][0]["request_text"] == "Remember this"


def test_root_redirects_to_app(tmp_path: Path) -> None:
    app = create_app(Store(tmp_path / "store"), FakeEngine())
    with _test_client(app) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/app/"


def test_authenticated_channel_routes_and_delivery_deduplication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "route-test-secret"
    monkeypatch.setenv("KIRO_ROUTE_SIGNING_SECRET", secret)
    monkeypatch.setenv("KIRO_ROUTE_VERIFY_TOKEN", "verify-me")
    app = create_app(Store(tmp_path / "store"), FakeEngine())
    with _test_client(app) as client:
        assert client.post(
            "/api/bots", json={"name": "builder", "cwd": str(tmp_path)}
        ).status_code == 201
        for kind in ("slack", "github", "email", "webhook"):
            response = client.post(
                "/api/channels",
                json={
                    "id": kind,
                    "name": kind.title(),
                    "kind": kind,
                    "bot_name": "builder",
                    "signing_secret_env": "KIRO_ROUTE_SIGNING_SECRET",
                    "trigger_prefix": "@kiro",
                },
            )
            assert response.status_code == 201
            assert "signing_secret_env" not in response.json()
        whatsapp_created = client.post(
            "/api/channels",
            json={
                "id": "whatsapp",
                "name": "WhatsApp",
                "kind": "whatsapp",
                "bot_name": "builder",
                "signing_secret_env": "KIRO_ROUTE_SIGNING_SECRET",
                "verify_token_env": "KIRO_ROUTE_VERIFY_TOKEN",
                "outbound_token_env": "",
            },
        )
        assert whatsapp_created.status_code == 201
        verified_whatsapp = client.get(
            "/hooks/whatsapp/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "12345",
            },
        )
        assert verified_whatsapp.status_code == 200 and verified_whatsapp.text == "12345"

        slack_raw = json.dumps(
            {"type": "url_verification", "challenge": "challenge-value"},
            separators=(",", ":"),
        ).encode()
        stamp = str(int(time.time()))
        slack_signature = "v0=" + hmac.new(
            secret.encode(), b"v0:" + stamp.encode() + b":" + slack_raw, hashlib.sha256
        ).hexdigest()
        verified = client.post(
            "/hooks/slack/slack",
            content=slack_raw,
            headers={
                "content-type": "application/json",
                "x-slack-request-timestamp": stamp,
                "x-slack-signature": slack_signature,
            },
        )
        assert verified.status_code == 200 and verified.text == "challenge-value"

        github_payload = {
            "action": "created",
            "repository": {"full_name": "acme/repo"},
            "sender": {"login": "arin", "type": "User"},
            "issue": {"number": 9, "title": "Investigate"},
            "comment": {"body": "@kiro please analyze"},
        }
        github_raw = json.dumps(github_payload, separators=(",", ":")).encode()
        github_signature = "sha256=" + hmac.new(
            secret.encode(), github_raw, hashlib.sha256
        ).hexdigest()
        headers = {
            "content-type": "application/json",
            "x-hub-signature-256": github_signature,
            "x-github-event": "issue_comment",
            "x-github-delivery": "delivery-9",
        }
        first = client.post("/hooks/github/github", content=github_raw, headers=headers)
        second = client.post("/hooks/github/github", content=github_raw, headers=headers)
        assert first.status_code == 200 and first.json()["accepted"] is True
        assert second.json()["duplicate"] is True

        generic_raw = json.dumps(
            {"delivery_id": "g1", "thread_id": "support-4", "sender": "arin", "text": "check this"},
            separators=(",", ":"),
        ).encode()
        generic_signature = "sha256=" + hmac.new(
            secret.encode(), stamp.encode() + b"." + generic_raw, hashlib.sha256
        ).hexdigest()
        accepted = client.post(
            "/hooks/webhook/webhook",
            content=generic_raw,
            headers={
                "content-type": "application/json",
                "x-kiro-timestamp": stamp,
                "x-kiro-signature-256": generic_signature,
            },
        )
        assert accepted.status_code == 200 and accepted.json()["accepted"] is True
        rejected = client.post(
            "/hooks/webhook/webhook",
            content=generic_raw,
            headers={
                "content-type": "application/json",
                "x-kiro-timestamp": stamp,
                "x-kiro-signature-256": "sha256=bad",
            },
        )
        assert rejected.status_code == 401

        whatsapp_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "123456"},
                                "messages": [
                                    {
                                        "from": "919999999999",
                                        "id": "wamid.route.1",
                                        "type": "text",
                                        "text": {"body": "Investigate this"},
                                    }
                                ],
                            },
                        }
                    ]
                }
            ],
        }
        whatsapp_raw = json.dumps(whatsapp_payload, separators=(",", ":")).encode()
        whatsapp_signature = "sha256=" + hmac.new(
            secret.encode(), whatsapp_raw, hashlib.sha256
        ).hexdigest()
        whatsapp = client.post(
            "/hooks/whatsapp/whatsapp",
            content=whatsapp_raw,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": whatsapp_signature,
            },
        )
        assert whatsapp.status_code == 200 and whatsapp.json()["accepted"] is True

        assert len(client.get("/api/channels").json()) == 5
        assert len(client.get("/api/channel-events").json()) == 3


def test_policy_routine_plugin_and_audit_routes(tmp_path: Path) -> None:
    engine = FakeEngine()
    app = create_app(Store(tmp_path / "store"), engine)
    with _test_client(app) as client:
        assert client.post(
            "/api/bots",
            json={"name": "builder", "cwd": str(tmp_path)},
        ).status_code == 201

        policy = client.put(
            "/api/bots/builder/policy",
            json={
                "approval_mode": "allow_list",
                "allowed_tools": ["filesystem.read"],
                "denied_tools": ["filesystem.delete"],
                "max_turns_per_hour": 10,
                "max_concurrent_runs": 2,
                "max_daily_runs": 50,
            },
        )
        assert policy.status_code == 200
        assert client.get("/api/bots/builder/policy").json()["max_daily_runs"] == 50

        routine = client.post(
            "/api/routines",
            json={
                "name": "Repository pulse",
                "bot_name": "builder",
                "prompt": "Summarize the repository status.",
                "trigger_kind": "interval",
                "interval_seconds": 300,
            },
        )
        assert routine.status_code == 201
        routine_id = routine.json()["id"]
        assert client.patch(
            f"/api/routines/{routine_id}", json={"enabled": False}
        ).status_code == 200
        assert len(client.get("/api/routines?bot_name=builder").json()) == 1

        plugin = client.post(
            "/api/plugins",
            json={
                "id": "local-tools",
                "name": "Local tools",
                "transport": "stdio",
                "command": "node",
                "args": ["server.js"],
                "env": {"SERVICE_TOKEN": "env:TEST_SERVICE_TOKEN"},
            },
        )
        assert plugin.status_code == 201
        assert plugin.json()["env"] == {"SERVICE_TOKEN": "env:TEST_SERVICE_TOKEN"}
        binding = client.put(
            "/api/bots/builder/plugins/local-tools",
            json={
                "allow_tools": ["read_status"],
                "deny_tools": [],
                "auto_approve_tools": ["read_status"],
                "timeout_ms": 20_000,
            },
        )
        assert binding.status_code == 200
        assert client.get("/api/bots/builder/plugins").json()[0]["plugin_id"] == "local-tools"

        lease = app.state.governance.reserve_run("builder", "manual-audit", actor="test")
        app.state.governance.finish_run(lease, actor="test")
        audit = client.get("/api/audit?bot_name=builder").json()
        assert [item["event_type"] for item in audit] == ["run_outcome", "run_submission"]

        assert client.delete(f"/api/routines/{routine_id}").status_code == 200
        assert client.delete("/api/bots/builder/plugins/local-tools").status_code == 200
        assert client.delete("/api/plugins/local-tools").status_code == 200


def test_delegation_plan_routes(tmp_path: Path) -> None:
    app = create_app(Store(tmp_path / "store"), FakeEngine())
    with _test_client(app) as client:
        for name in ("researcher", "builder"):
            assert client.post(
                "/api/bots", json={"name": name, "cwd": str(tmp_path)}
            ).status_code == 201
        created = client.post(
            "/api/delegations",
            json={
                "name": "Research then build",
                "nodes": [
                    {"id": "research", "bot_name": "researcher", "prompt": "Investigate"},
                    {"id": "build", "bot_name": "builder", "prompt": "Implement"},
                ],
                "edges": [{"source": "research", "target": "build"}],
                "start": False,
            },
        )
        assert created.status_code == 201
        payload = created.json()
        plan_id = payload["plan"]["id"]
        assert payload["plan"]["status"] == "paused"
        assert [node["id"] for node in payload["nodes"]] == ["research", "build"]
        assert client.get(f"/api/delegations/{plan_id}").status_code == 200
        assert len(client.get("/api/delegations").json()) == 1
        started = client.post(f"/api/delegations/{plan_id}/start")
        assert started.status_code == 200
        assert started.json()["plan"]["status"] in {"pending", "running", "succeeded"}
        assert client.post(f"/api/delegations/{plan_id}/cancel").json()["plan"]["status"] == "cancelled"


def test_isolated_workspace_routes_retain_material_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)

    app = create_app(Store(tmp_path / "store"), FakeEngine())
    with _test_client(app) as client:
        created = client.post(
            "/api/workspaces",
            json={"repo_path": str(repo), "ref": "HEAD", "run_id": "isolated-1"},
        )
        assert created.status_code == 201
        lease = created.json()
        worktree = Path(lease["path"])
        (worktree / "artifact.txt").write_text("material output\n")
        finalized = client.post(
            "/api/workspaces/isolated-1/finalize",
            json={"token": lease["token"], "artifact_paths": ["artifact.txt"]},
        )
        assert finalized.status_code == 200
        assert finalized.json()["artifacts"][0]["path"] == "artifact.txt"
        retained = client.post(
            "/api/workspaces/isolated-1/cleanup", json={"token": lease["token"]}
        )
        assert retained.status_code == 409
        assert worktree.exists()


def test_coding_lifecycle_routes_stop_at_human_handoff(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    coding = FakeCodingController()
    app = create_app(store, FakeEngine(), coding_controller=coding)
    with _test_client(app) as client:
        for name in ("builder", "reviewer"):
            assert client.post(
                "/api/bots", json={"name": name, "cwd": str(tmp_path)}
            ).status_code == 201
        accepted = client.post(
            "/api/coding-executions",
            json={
                "idempotency_key": "issue-42",
                "repo_path": str(tmp_path),
                "task": "Implement and test the change",
                "builder_bot": "builder",
                "reviewer_bot": "reviewer",
                "checks": [{"name": "tests", "argv": ["pytest", "-q"]}],
                "max_repairs": 1,
            },
        )
        assert accepted.status_code == 202
        assert accepted.json()["status"] == "queued"
        spec, key = coding.submissions[0]
        assert key == "issue-42"
        assert spec.builder_bot == "builder" and spec.reviewer_bot == "reviewer"
        assert spec.checks[0].argv == ("pytest", "-q")

        assert client.get("/api/coding-executions").json()[0]["status"] == "awaiting_handoff"
        assert client.get("/api/coding-executions/coding-1").status_code == 200
        approved = client.post(
            "/api/coding-executions/coding-1/approve",
            json={"expected_version": 4},
        )
        assert approved.json()["status"] == "ready"
        assert client.post("/api/coding-executions/coding-1/cancel").json()["status"] == "cancelled"
    assert coding.started and coding.closed
