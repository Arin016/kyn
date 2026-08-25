from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

import pytest

from kiro_bot.channels import (
    ChannelAuthenticationError,
    ChannelAuthorizationError,
    ChannelGateway,
    ChannelStore,
    IncomingEvent,
    ProviderReplyDeliverer,
    email_event,
    generic_event,
    github_event,
    slack_event,
    verify_kiro_webhook,
    verify_sha256,
    verify_slack,
    whatsapp_events,
)
from kiro_bot.memory import SharedMemoryStore
from kiro_bot.store import Bot, Store


def _channels(tmp_path: Path) -> tuple[Store, ChannelStore]:
    store = Store(tmp_path / "state")
    store.put_bot(Bot("builder", str(tmp_path)))
    return store, ChannelStore(store)


def _binding(channels: ChannelStore, **changes: Any) -> Any:
    values = {
        "binding_id": "external",
        "name": "External",
        "kind": "webhook",
        "bot_name": "builder",
        "signing_secret_env": "KIRO_TEST_SIGNING_SECRET",
    }
    values.update(changes)
    return channels.create_binding(**values)


def test_bindings_persist_references_not_secrets_and_enforce_scope(tmp_path: Path) -> None:
    store, channels = _channels(tmp_path)
    binding = _binding(
        channels,
        allowed_sources=("project-a",),
        allowed_senders=("arin",),
    )
    assert "signing_secret_env" not in binding.summary()
    assert binding.summary()["signing_secret_configured"] is True
    assert b"super-secret-value" not in store.path.read_bytes()

    incoming = IncomingEvent("d1", "thread", "arin", "project-a", "work", {})
    event, created = channels.accept(binding, incoming)
    duplicate, duplicate_created = channels.accept(binding, incoming)
    assert created is True and duplicate_created is False
    assert duplicate.id == event.id

    with pytest.raises(ChannelAuthorizationError):
        channels.accept(
            binding, IncomingEvent("d2", "thread", "mallory", "project-a", "work", {})
        )


def test_official_github_signature_vector_and_replay_safe_signatures() -> None:
    verify_sha256(
        b"Hello, World!",
        "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17",
        "It's a Secret to Everybody",
    )
    raw = b'{"event":"hello"}'
    stamp = "1700000000"
    slack_signature = "v0=" + hmac.new(
        b"secret", b"v0:" + stamp.encode() + b":" + raw, hashlib.sha256
    ).hexdigest()
    verify_slack(raw, stamp, slack_signature, "secret", now=1700000000)
    with pytest.raises(ChannelAuthenticationError):
        verify_slack(raw, stamp, slack_signature, "secret", now=1700000601)

    webhook_signature = "sha256=" + hmac.new(
        b"secret", stamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    verify_kiro_webhook(raw, stamp, webhook_signature, "secret", now=1700000000)


def test_provider_normalizers_keep_thread_identity_and_ignore_noise(tmp_path: Path) -> None:
    _, channels = _channels(tmp_path)
    slack_binding = _binding(channels, binding_id="slack", kind="slack")
    slack = slack_event(
        {
            "type": "event_callback",
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {"type": "app_mention", "channel": "C1", "user": "U1", "ts": "10", "text": "help"},
        },
        slack_binding,
    )
    assert slack is not None and slack.thread_key == "T1:C1:10"
    assert slack_event(
        {"type": "event_callback", "event": {"type": "message", "bot_id": "B1", "text": "@kiro loop"}},
        slack_binding,
    ) is None

    github_binding = _binding(channels, binding_id="github", kind="github")
    github = github_event(
        {
            "action": "created",
            "repository": {"full_name": "acme/repo"},
            "sender": {"login": "arin", "type": "User"},
            "issue": {"number": 7, "title": "Bug"},
            "comment": {"body": "@kiro investigate this"},
        },
        "issue_comment",
        "delivery-1",
        github_binding,
    )
    assert github is not None and github.thread_key == "acme/repo#7"

    email = email_event(
        {"message_id": "m1", "from": "a@example.com", "to": "bot@example.com", "subject": "Hi", "text": "Please help"}
    )
    assert email.thread_key == "m1" and "Subject: Hi" in email.text
    generic = generic_event(
        {"delivery_id": "x", "thread_id": "t", "sender": "arin", "text": "do it", "context": {"ticket": 9}}
    )
    assert generic.context == {"ticket": 9}


def test_whatsapp_binding_normalization_and_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, channels = _channels(tmp_path)
    with pytest.raises(ValueError, match="environment variable"):
        _binding(channels, binding_id="wa-invalid", kind="whatsapp")
    binding = _binding(
        channels,
        binding_id="whatsapp",
        kind="whatsapp",
        verify_token_env="KIRO_WA_VERIFY",
        outbound_token_env="KIRO_WA_ACCESS",
    )
    normalized = whatsapp_events(
        {
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
                                        "id": "wamid.1",
                                        "type": "text",
                                        "text": {"body": "Please inspect this"},
                                    },
                                    {
                                        "from": "919999999999",
                                        "id": "wamid.2",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {"id": "yes", "title": "Approve"},
                                        },
                                    },
                                ],
                            },
                        }
                    ]
                }
            ],
        }
    )
    assert [item.delivery_id for item in normalized] == ["wamid.1", "wamid.2"]
    assert normalized[0].thread_key == "123456:919999999999"
    assert normalized[1].text == "Approve"

    event, _ = channels.accept(binding, normalized[0])
    calls: list[tuple[str, dict[str, Any], dict[str, str], str]] = []

    def fake_post(url: str, payload: dict[str, Any], headers: dict[str, str], provider: str) -> None:
        calls.append((url, payload, headers, provider))

    monkeypatch.setenv("KIRO_WA_ACCESS", "access-token")
    monkeypatch.setenv("KIRO_META_GRAPH_API_VERSION", "v25.0")
    monkeypatch.setattr("kiro_bot.channels._post_json", fake_post)
    asyncio.run(ProviderReplyDeliverer().deliver(binding, event, "answer"))
    assert calls[0][0] == "https://graph.facebook.com/v25.0/123456/messages"
    assert calls[0][1]["to"] == "919999999999"
    assert calls[0][1]["context"] == {"message_id": "wamid.1"}
    assert calls[0][2]["Authorization"] == "Bearer access-token"


class _Deliverer:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def deliver(self, _binding: Any, _event: Any, response: str) -> str:
        self.replies.append(response)
        return "delivered"


def test_gateway_preserves_bounded_source_thread_context(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, channels = _channels(tmp_path)
        binding = _binding(channels)
        prompts: list[str] = []
        deliverer = _Deliverer()

        async def submit(bot: str, prompt: str, actor: str) -> str:
            assert bot == "builder" and actor == "channel:webhook:external"
            prompts.append(prompt)
            return f"run-{len(prompts)}"

        async def wait(run_id: str) -> dict[str, Any]:
            return {
                "status": "complete",
                "events": [{"kind": "text", "text": f"answer-{run_id}"}],
            }

        gateway = ChannelGateway(channels, submit, wait, deliverer=deliverer)
        await gateway.start()
        try:
            first, _ = await gateway.ingest(
                binding, IncomingEvent("d1", "thread", "arin", "source", "first request", {})
            )
            await _wait_status(channels, first.id, "responded")
            second, _ = await gateway.ingest(
                binding, IncomingEvent("d2", "thread", "arin", "source", "second request", {})
            )
            await _wait_status(channels, second.id, "responded")
        finally:
            await gateway.close()

        assert "first request" in prompts[1]
        assert "answer-run-1" in prompts[1]
        assert "second request" in prompts[1]
        assert deliverer.replies == ["answer-run-1", "answer-run-2"]

    asyncio.run(scenario())


def test_gateway_retrieves_shared_memory_and_records_completed_exchange(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store, channels = _channels(tmp_path)
        binding = _binding(channels)
        memory = SharedMemoryStore(store)
        memory.record(
            "builder",
            "local",
            "api",
            "Use a segment tree for context navigation",
            "That is the selected architecture.",
            event_id="local-decision",
        )
        prompts: list[str] = []

        async def submit(_bot: str, prompt: str, _actor: str) -> str:
            prompts.append(prompt)
            return "run-memory"

        async def wait(_run_id: str) -> dict[str, Any]:
            return {
                "status": "complete",
                "events": [{"kind": "text", "text": "Continuing with the segment tree."}],
            }

        gateway = ChannelGateway(
            channels,
            submit,
            wait,
            deliverer=_Deliverer(),
            memory=memory,
        )
        await gateway.start()
        try:
            event, _ = await gateway.ingest(
                binding,
                IncomingEvent(
                    "memory-1",
                    "thread",
                    "arin",
                    "source",
                    "Continue the context architecture",
                    {},
                ),
            )
            await _wait_status(channels, event.id, "responded")
        finally:
            await gateway.close()

        assert "Use a segment tree" in prompts[0]
        assert prompts[0].endswith("Latest request from arin:\nContinue the context architecture")
        recorded = [
            item
            for item in memory.list_events("builder")
            if item.scope.startswith("channel:webhook:external:")
        ]
        assert len(recorded) == 1
        assert recorded[0].request_text == "Continue the context architecture"
        assert recorded[0].response_text == "Continuing with the segment tree."

    asyncio.run(scenario())


def test_gateway_recovers_accepted_events_without_resubmission_after_run_attach(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, channels = _channels(tmp_path)
        binding = _binding(channels)
        event, _ = channels.accept(
            binding, IncomingEvent("d1", "thread", "arin", "source", "resume", {})
        )
        channels.attach_run(event.id, "existing-run")
        submitted: list[str] = []

        async def submit(_bot: str, _prompt: str, _actor: str) -> str:
            submitted.append("called")
            return "new-run"

        async def wait(run_id: str) -> dict[str, Any]:
            assert run_id == "existing-run"
            return {"status": "complete", "response_text": "recovered"}

        gateway = ChannelGateway(channels, submit, wait, deliverer=_Deliverer())
        await gateway.start()
        await _wait_status(channels, event.id, "responded")
        await gateway.close()
        assert submitted == []

    asyncio.run(scenario())


async def _wait_status(channels: ChannelStore, event_id: str, status: str) -> None:
    for _ in range(200):
        event = channels.get_event(event_id)
        if event is not None and event.status == status:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"channel event did not reach {status}")
