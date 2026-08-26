from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from kyn.runtime import AcpRuntime


def test_prompt_stream_and_demux(tmp_path: Path) -> None:
    async def scenario() -> None:
        fake = Path(__file__).with_name("fake_kiro.py")
        runtime = AcpRuntime(tmp_path, command=[sys.executable, str(fake)])
        await runtime.start()
        try:
            session = await runtime.create_session()
            events = [event async for event in session.prompt("hello")]
            assert [event.kind for event in events] == ["text", "complete"]
            assert events[0].text == "hello from fake Kiro"
            assert events[1].stop_reason == "end_turn"
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_permission_round_trip(tmp_path: Path) -> None:
    async def scenario() -> None:
        fake = Path(__file__).with_name("fake_kiro.py")
        runtime = AcpRuntime(tmp_path, command=[sys.executable, str(fake)])
        await runtime.start()
        try:
            session = await runtime.create_session()
            events = []
            async for event in session.prompt("permission"):
                events.append(event)
                if event.kind == "permission":
                    assert event.tool_name == "write"
                    assert event.mcp_server_name == "workspace"
                    await session.approve(event.request_id)
            assert [event.kind for event in events] == [
                "tool_call",
                "permission",
                "text",
                "complete",
            ]
            assert events[2].text == "approved"
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_acp_trace_recursively_redacts_launch_secrets(monkeypatch, capsys) -> None:
    monkeypatch.setenv("KYN_TRACE", "1")
    AcpRuntime._trace(
        "->",
        {
            "method": "session/new",
            "params": {
                "mcpServers": [
                    {
                        "name": "github",
                        "env": [
                            {"name": "GITHUB_TOKEN", "value": "env-secret-value"},
                            {"name": "PATH", "value": "/sensitive/path"},
                        ],
                        "headers": {
                            "Authorization": "Bearer header-secret",
                            "X-Api-Version": "secret-version",
                        },
                    }
                ],
                "access_token": "direct-token-value",
                "password": "direct-password-value",
            },
        },
    )
    output = capsys.readouterr().err
    assert "github" in output
    assert "GITHUB_TOKEN" in output
    for secret in (
        "env-secret-value",
        "/sensitive/path",
        "header-secret",
        "secret-version",
        "direct-token-value",
        "direct-password-value",
    ):
        assert secret not in output
    assert output.count("<redacted>") >= 6
