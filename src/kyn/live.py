"""In-process fan-out for control-room live updates."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping


class LiveBus:
    def __init__(self, *, max_queue: int = 256) -> None:
        self._max_queue = max(8, int(max_queue))
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, payload: Mapping[str, Any]) -> None:
        message = dict(payload)
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)
