from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def default_home() -> Path:
    return Path(os.environ.get("KIRO_BOT_HOME", "~/.kiro-bot")).expanduser()


@dataclass(slots=True)
class Bot:
    name: str
    cwd: str
    agent: str = ""
    model: str = ""
    effort: str = ""
    mcp_servers: list[dict[str, Any]] | None = None


class Store:
    def __init__(self, home: str | Path | None = None) -> None:
        self.home = Path(home).expanduser() if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "kiro-bot.db"
        self._migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def put_bot(self, bot: Bot) -> None:
        now = _now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO bots(name, cwd, agent, model, effort, mcp_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    cwd=excluded.cwd, agent=excluded.agent, model=excluded.model,
                    effort=excluded.effort, mcp_json=excluded.mcp_json, updated_at=excluded.updated_at
                """,
                (
                    bot.name,
                    bot.cwd,
                    bot.agent,
                    bot.model,
                    bot.effort,
                    json.dumps(bot.mcp_servers or []),
                    now,
                    now,
                ),
            )

    def get_bot(self, name: str) -> Bot | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM bots WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return Bot(
            name=row["name"],
            cwd=row["cwd"],
            agent=row["agent"],
            model=row["model"],
            effort=row["effort"],
            mcp_servers=json.loads(row["mcp_json"] or "[]"),
        )

    def list_bots(self) -> list[Bot]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM bots ORDER BY name").fetchall()
        return [
            Bot(
                name=row["name"],
                cwd=row["cwd"],
                agent=row["agent"],
                model=row["model"],
                effort=row["effort"],
                mcp_servers=json.loads(row["mcp_json"] or "[]"),
            )
            for row in rows
        ]

    def conversation(self, bot_name: str) -> tuple[str, str] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT session_id, transcript_path FROM conversations WHERE bot_name = ?",
                (bot_name,),
            ).fetchone()
        return (row["session_id"], row["transcript_path"]) if row else None

    def save_conversation(self, bot_name: str, session_id: str, transcript_path: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO conversations(bot_name, session_id, transcript_path, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(bot_name) DO UPDATE SET
                    session_id=excluded.session_id,
                    transcript_path=excluded.transcript_path,
                    updated_at=excluded.updated_at
                """,
                (bot_name, session_id, transcript_path, _now()),
            )

    def begin_turn(self, bot_name: str, prompt: str) -> int:
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO turns(bot_name, prompt, started_at) VALUES (?, ?, ?)",
                (bot_name, prompt, _now()),
            )
            return int(cursor.lastrowid)

    def add_event(self, turn_id: int, sequence: int, event: Any) -> None:
        payload = {
            "kind": event.kind,
            "text": event.text,
            "title": event.title,
            "tool_call_id": event.tool_call_id,
            "request_id": event.request_id,
            "options": event.options,
            "stop_reason": event.stop_reason,
            "tool_name": event.tool_name,
            "mcp_server_name": event.mcp_server_name,
            "raw": event.raw,
        }
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(turn_id, sequence, kind, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (turn_id, sequence, event.kind, json.dumps(payload), _now()),
            )

    def finish_turn(self, turn_id: int, status: str, stop_reason: str = "") -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE turns SET status = ?, stop_reason = ?, finished_at = ? WHERE id = ?",
                (status, stop_reason, _now(), turn_id),
            )

    def history(self, bot_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent durable turns in chronological order with their events."""
        bounded = min(max(int(limit), 1), 500)
        with self.connect() as db:
            turns = db.execute(
                """
                SELECT id, bot_name, prompt, status, stop_reason,
                       started_at, finished_at
                FROM turns
                WHERE bot_name = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (bot_name, bounded),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for turn in reversed(turns):
                events = db.execute(
                    """
                    SELECT sequence, kind, payload_json, created_at
                    FROM events WHERE turn_id = ? ORDER BY sequence
                    """,
                    (turn["id"],),
                ).fetchall()
                result.append(
                    {
                        "id": turn["id"],
                        "bot_name": turn["bot_name"],
                        "prompt": turn["prompt"],
                        "status": turn["status"],
                        "stop_reason": turn["stop_reason"],
                        "started_at": turn["started_at"],
                        "finished_at": turn["finished_at"],
                        "events": [
                            {
                                "sequence": event["sequence"],
                                "kind": event["kind"],
                                "created_at": event["created_at"],
                                **json.loads(event["payload_json"]),
                            }
                            for event in events
                        ],
                    }
                )
        return result

    def _migrate(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS bots (
                    name TEXT PRIMARY KEY,
                    cwd TEXT NOT NULL,
                    agent TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    effort TEXT NOT NULL DEFAULT '',
                    mcp_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    bot_name TEXT PRIMARY KEY REFERENCES bots(name) ON DELETE CASCADE,
                    session_id TEXT NOT NULL,
                    transcript_path TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_name TEXT NOT NULL REFERENCES bots(name) ON DELETE CASCADE,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    stop_reason TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(turn_id, sequence)
                );
                """
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
