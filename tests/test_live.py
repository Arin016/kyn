from __future__ import annotations

from kyn.live import LiveBus


def test_slow_subscriber_drops_oldest_instead_of_unsubscribing() -> None:
    bus = LiveBus(max_queue=4)
    slow = bus.subscribe()
    for index in range(10):
        bus.publish({"type": "roster", "n": index})
    # Still subscribed, holding the newest — never silently discarded.
    assert not slow.empty()
    last = None
    while not slow.empty():
        last = slow.get_nowait()
    assert last is not None and last["n"] == 9
    assert slow in bus._subscribers


def test_publish_reaches_all_subscribers() -> None:
    bus = LiveBus()
    first = bus.subscribe()
    second = bus.subscribe()
    bus.publish({"type": "ping"})
    assert first.get_nowait() == {"type": "ping"}
    assert second.get_nowait() == {"type": "ping"}
    bus.unsubscribe(first)
    bus.publish({"type": "ping"})
    assert first.empty()
    assert second.get_nowait() == {"type": "ping"}
