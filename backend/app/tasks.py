"""Fire-and-forget background tasks that are neither garbage-collected nor silently lost (0008).

The event loop only weakly references tasks, so a bare ``asyncio.create_task(...)`` with no saved
reference can be collected mid-run, and an exception inside it surfaces (at best) as a "Task
exception was never retrieved" warning at GC time. :func:`spawn` keeps a strong reference until
the task finishes and logs any crash with its traceback.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

logger = logging.getLogger(__name__)

_running: set[asyncio.Task] = set()


def spawn(coro: Coroutine, *, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _running.add(task)
    task.add_done_callback(_finished)
    return task


def running() -> set[asyncio.Task]:
    return set(_running)


def _finished(task: asyncio.Task) -> None:
    _running.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("background task %s crashed", task.get_name(), exc_info=exc)
