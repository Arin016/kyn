from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .engine import Engine
from .runtime import AcpError
from .store import Bot, Store


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="kyn", description="KYN — persistent local agents on Kiro")
    commands = root.add_subparsers(dest="command", required=True)

    bot = commands.add_parser("bot", help="manage named bots")
    bot_commands = bot.add_subparsers(dest="bot_command", required=True)
    create = bot_commands.add_parser("create", help="create or update a bot")
    create.add_argument("name")
    create.add_argument("--cwd", default=os.getcwd())
    create.add_argument("--agent", default="")
    create.add_argument("--model", default="")
    create.add_argument("--effort", default="")
    bot_commands.add_parser("list", help="list bots")

    ask = commands.add_parser("ask", help="run one turn")
    ask.add_argument("bot")
    ask.add_argument("message")

    chat = commands.add_parser("chat", help="open an interactive conversation")
    chat.add_argument("bot")

    serve = commands.add_parser("serve", help="run the persistent local control room")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)

    hooks = commands.add_parser(
        "serve-hooks", help="run a public-tunnel-safe hooks-only relay"
    )
    hooks.add_argument("--host", default="127.0.0.1")
    hooks.add_argument("--port", default=8766, type=int)
    hooks.add_argument("--upstream-port", default=8765, type=int)

    return root


def main() -> None:
    args = parser().parse_args()
    try:
        if args.command == "bot":
            _bot_command(args)
        elif args.command == "ask":
            asyncio.run(_ask(args.bot, args.message))
        elif args.command == "chat":
            asyncio.run(_chat(args.bot))
        elif args.command == "serve":
            _serve(args.host, args.port)
        elif args.command == "serve-hooks":
            _serve_hooks(args.host, args.port, args.upstream_port)
    except (AcpError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nStopped.")


def _bot_command(args: argparse.Namespace) -> None:
    store = Store()
    if args.bot_command == "create":
        cwd = str(Path(args.cwd).expanduser().resolve())
        store.put_bot(
            Bot(
                name=args.name,
                cwd=cwd,
                agent=args.agent,
                model=args.model,
                effort=args.effort,
            )
        )
        print(f"Saved bot {args.name!r} for {cwd}")
        return
    for bot in store.list_bots():
        details = [bot.cwd]
        if bot.agent:
            details.append(f"agent={bot.agent}")
        if bot.model:
            details.append(f"model={bot.model}")
        print(f"{bot.name}\t" + "  ".join(details))


async def _ask(bot_name: str, message: str) -> None:
    engine = Engine(store=Store(), recover_on_start=False)
    await engine.start()
    try:
        run_id = await engine.submit(bot_name, message, actor="cli")
        await _render_engine_run(engine, run_id)
    finally:
        await engine.close()


async def _chat(bot_name: str) -> None:
    engine = Engine(store=Store(), recover_on_start=False)
    await engine.start()
    try:
        print(f"Connected to governed bot {bot_name!r}. Type /exit to stop.")
        while True:
            message = await asyncio.to_thread(input, "\nyou> ")
            if message.strip() in {"/exit", "/quit"}:
                return
            if not message.strip():
                continue
            run_id = await engine.submit(bot_name, message, actor="cli")
            await _render_engine_run(engine, run_id)
    finally:
        await engine.close()


async def _render_engine_run(engine: Engine, run_id: str) -> None:
    printed_prefix = False
    async for event in engine.subscribe(run_id):
        kind = str(event.get("kind") or "")
        if kind == "text":
            if not printed_prefix:
                print("bot> ", end="", flush=True)
                printed_prefix = True
            print(str(event.get("text") or ""), end="", flush=True)
        elif kind == "permission":
            if printed_prefix:
                print()
                printed_prefix = False
            answer = await asyncio.to_thread(
                input,
                f"Allow tool '{event.get('title') or 'Tool request'}' once? [y/N]: ",
            )
            request_id = event.get("request_id")
            if answer.strip().lower() in {"y", "yes"}:
                await engine.decide_permission(run_id, request_id, "once")
            else:
                await engine.decide_permission(run_id, request_id, "reject")
        elif kind == "tool_call":
            if printed_prefix:
                print()
                printed_prefix = False
            print(f"[tool] {event.get('title') or event.get('tool_call_id')}")
        elif kind == "complete":
            if printed_prefix:
                print()
                printed_prefix = False
            stop_reason = str(event.get("stop_reason") or "")
            if stop_reason not in {"", "end_turn"}:
                print(f"[stopped: {stop_reason}]")
        elif os.environ.get("KYN_DEBUG") == "1":
            print(f"\n[{kind}] {json.dumps(event, ensure_ascii=False)}")
    snapshot = await engine.get_run(run_id)
    if snapshot["status"] == "failed":
        raise AcpError(snapshot["error"] or "Kiro run failed")


def _serve(host: str, port: int) -> None:
    host = os.environ.get("KYN_HOST", host)
    env_port = os.environ.get("PORT") or os.environ.get("KYN_PORT")
    if env_port:
        port = int(env_port)
    if not 1 <= port <= 65535:
        raise AcpError("port must be between 1 and 65535")
    os.environ.setdefault("KYN_CONTROL_URL", f"http://127.0.0.1:{port}")
    try:
        import uvicorn

        from .server import create_app
    except ImportError as exc:
        raise AcpError(
            "The browser control room is not installed. "
            "Run: python3 -m pip install -e '.[server]'"
        ) from exc
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


def _serve_hooks(host: str, port: int, upstream_port: int) -> None:
    if not 1 <= port <= 65535 or not 1 <= upstream_port <= 65535:
        raise AcpError("ports must be between 1 and 65535")
    try:
        import uvicorn

        from .hook_gateway import create_hook_gateway
    except ImportError as exc:
        raise AcpError(
            "The hooks gateway is not installed. Run: uv sync --extra server"
        ) from exc
    app = create_hook_gateway(upstream_port=upstream_port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
