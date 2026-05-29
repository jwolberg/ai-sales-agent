"""In-process live event bus (IR7-T2).

A tiny pub/sub so the dashboard can stream calls as they happen. The recorder publishes events
(call_started, turn, decision, kpi, call_ended) from wherever a call runs — including a worker
thread (the voice pipeline) — and SSE subscribers in the FastAPI event loop receive them.

Thread-safe by design: each subscription captures its event loop, and ``publish`` (callable from any
thread) hands delivery to that loop via ``call_soon_threadsafe``. With no subscribers, publishing is
a cheap no-op, so the recorder pays nothing in tests / offline runs.
"""

from __future__ import annotations

import asyncio


class Subscription:
    """One SSE listener's queue, optionally filtered to a single call."""

    def __init__(self, call_id: str | None = None, *, maxsize: int = 1000) -> None:
        self.call_id = call_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._loop = asyncio.get_running_loop()

    def _deliver(self, event: dict) -> None:
        if self.call_id is not None and event.get("call_id") != self.call_id:
            return
        try:
            self._loop.call_soon_threadsafe(self._put, event)
        except RuntimeError:
            pass  # loop closed

    def _put(self, event: dict) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # a slow client must not back-pressure the call


class EventBus:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()

    def subscribe(self, call_id: str | None = None) -> Subscription:
        sub = Subscription(call_id)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(self, **event) -> None:
        """Fan an event out to all matching subscribers. Safe from any thread."""
        for sub in list(self._subs):
            sub._deliver(event)


# Process-wide singleton.
bus = EventBus()
