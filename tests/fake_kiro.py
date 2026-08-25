from __future__ import annotations

import json
import sys


def send(message: dict) -> None:
    print(json.dumps(message), flush=True)


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params", {})
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"agentCapabilities": {"loadSession": True}}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "fake-session"}})
    elif method == "session/load":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"modes": {"availableModes": []}}})
    elif method == "session/prompt":
        session_id = params["sessionId"]
        prompt = params.get("prompt", [])
        prompt_text = prompt[0].get("text", "") if prompt else ""
        if prompt_text == "permission":
            send({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "tool-1",
                        "title": "Write a file",
                        "_meta": {
                            "kiro": {
                                "toolName": "write",
                                "mcpServerName": "workspace",
                            }
                        },
                    },
                },
            })
            send({
                "jsonrpc": "2.0",
                "id": "permission-1",
                "method": "session/request_permission",
                "params": {
                    "sessionId": session_id,
                    "toolCall": {"toolCallId": "tool-1", "title": "Write a file"},
                    "options": [
                        {"optionId": "allow_once", "name": "Allow once"},
                        {"optionId": "reject", "name": "Reject"},
                    ],
                },
            })
            continue
        send({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "hello from fake Kiro"},
                },
            },
        })
        send({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}})
    elif method == "_kiro.dev/session/terminate":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif request_id == "permission-1" and "result" in request:
        send({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fake-session",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "approved"},
                },
            },
        })
        send({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})
