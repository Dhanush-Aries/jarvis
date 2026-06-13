"""Tiny in-process async event bus. Interfaces subscribe to streamed updates."""
from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def emit(self, kind: str, **data: Any) -> None:
        event = {"kind": kind, **data}
        for q in list(self._subscribers):
            await q.put(event)


bus = EventBus()
