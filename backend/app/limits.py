"""Spend/abuse limits on the two things that cost real money per request (ticket 0003).

- :data:`sms_budget` caps payment-link texts per call and per destination number per hour, across
  both send paths (the engine's caller-ID auto-text and the dashboard's manual send) — so a buggy
  loop or a leaked credential can't turn the Twilio account into an SMS relay.
- :data:`session_slots` caps concurrent paid sessions (browser voice, Twilio calls, simulated
  calls), each of which drives STT/LLM/TTS spend for its whole duration.

In-memory and per-process on purpose: the service runs as a single instance
(``--max-instances 1``, in-process event bus). Scaling out would need a shared store (Redis).
Thread-safe because the engine runs turns in worker threads (``asyncio.to_thread``).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

_HOUR = 3600.0


class SmsBudget:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._per_call: dict[str, int] = defaultdict(int)
        self._per_number: dict[str, deque[float]] = defaultdict(deque)

    def try_acquire(
        self, call_id: str | None, to: str, *, per_call: int, per_number_per_hour: int
    ) -> bool:
        """Record one send and return True, or return False (recording nothing) if over a cap."""
        now = self._clock()
        with self._lock:
            sent = self._per_number[to]
            while sent and now - sent[0] >= _HOUR:
                sent.popleft()
            if len(sent) >= per_number_per_hour:
                return False
            if call_id is not None and self._per_call[call_id] >= per_call:
                return False
            sent.append(now)
            if call_id is not None:
                self._per_call[call_id] += 1
            return True


class SessionSlots:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0

    def try_acquire(self, *, limit: int) -> bool:
        with self._lock:
            if self.active >= limit:
                return False
            self.active += 1
            return True

    def release(self) -> None:
        with self._lock:
            self.active = max(0, self.active - 1)


sms_budget = SmsBudget()
session_slots = SessionSlots()


def allow_sms(settings, call_id: str | None, to: str) -> bool:
    return sms_budget.try_acquire(
        call_id,
        to,
        per_call=settings.sms_max_per_call,
        per_number_per_hour=settings.sms_max_per_number_per_hour,
    )


def reset() -> None:
    """Fresh limiter state (tests)."""
    global sms_budget, session_slots
    sms_budget = SmsBudget()
    session_slots = SessionSlots()
