from __future__ import annotations

from kyn.protocol import Event
from kyn.store import Bot, Store


def test_bot_and_conversation_persistence(tmp_path) -> None:
    store = Store(tmp_path)
    store.put_bot(Bot(name="builder", cwd=str(tmp_path), model="auto"))
    store.save_conversation("builder", "session-1", "/tmp/session-1.json")

    reopened = Store(tmp_path)
    bot = reopened.get_bot("builder")
    assert bot is not None
    assert bot.model == "auto"
    assert reopened.conversation("builder") == ("session-1", "/tmp/session-1.json")


def test_history_is_chronological_and_includes_events(tmp_path) -> None:
    store = Store(tmp_path)
    store.put_bot(Bot(name="builder", cwd=str(tmp_path)))
    first = store.begin_turn("builder", "first")
    store.add_event(first, 1, Event(kind="text", text="one"))
    store.finish_turn(first, "complete", "end_turn")
    second = store.begin_turn("builder", "second")
    store.add_event(second, 1, Event(kind="text", text="two"))
    store.finish_turn(second, "complete", "end_turn")

    history = store.history("builder")
    assert [turn["prompt"] for turn in history] == ["first", "second"]
    assert history[0]["events"][0]["text"] == "one"
