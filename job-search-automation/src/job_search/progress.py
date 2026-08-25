"""Thread-safe pub/sub used to push live progress updates from background
work out to WebSocket clients.

Both CV generation (POST /jobs/{id}/send-cv) and a pipeline run (POST /run)
execute via Starlette's BackgroundTasks, which runs sync callables in a
worker thread - not on the asyncio event loop. asyncio.Queue is not
thread-safe, so publish() hops onto the loop via call_soon_threadsafe
rather than touching subscriber queues directly from a worker thread.

One hub instance is shared for the whole app (see api.py). Channels are
just string keys: "cv:<job_id>" per CV generation, "run" for the singleton
pipeline run.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class ProgressHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        # Last message per channel, so a client that connects *after* work
        # already started (or after it already finished) still gets the
        # current state immediately instead of waiting for the next event
        # that may never come (e.g. connecting right after "done" fires).
        self._last: dict[str, dict[str, Any]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Call once at app startup (see api.py's startup event) - captures
        the main event loop so publish() can target it from any thread."""
        self._loop = loop

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[channel].append(queue)
        last = self._last.get(channel)
        if last is not None:
            queue.put_nowait(last)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(channel)
        if subs and queue in subs:
            subs.remove(queue)
        if subs is not None and not subs:
            self._subscribers.pop(channel, None)

    def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Thread-safe - safe to call from a BackgroundTasks worker thread,
        which is the only place this is ever called from in practice."""
        self._last[channel] = message
        if self._loop is None:
            # No event loop bound yet (e.g. called from a script/test
            # outside the API). Still record `_last` above so a later
            # subscriber sees the final state; just nothing to wake up.
            return
        for queue in list(self._subscribers.get(channel, [])):
            self._loop.call_soon_threadsafe(queue.put_nowait, message)

    def clear(self, channel: str) -> None:
        """Drop cached last-state for a channel (e.g. once a CV job's
        result has been delivered and there's no reason to keep replaying
        it to new subscribers)."""
        self._last.pop(channel, None)


# Single shared instance for the whole app.
hub = ProgressHub()
