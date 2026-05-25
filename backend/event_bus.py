"""
Async Event Bus — pub/sub decoupler between data engines and WS broadcaster.
Publishers call publish() (sync-safe from threads) or apublish() (async).
Subscribers get an async generator via subscribe().
"""

import asyncio
from collections import defaultdict
from typing import AsyncIterator, Dict, List
import logging

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._queues: Dict[str, List[asyncio.Queue]] = defaultdict(list)

    # ── Publishers ──────────────────────────────────────────────────────────

    def publish(self, event_type: str, payload: dict) -> None:
        """Thread-safe fire-and-forget publish (from sync context / threads)."""
        for queue in self._queues[event_type]:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("EventBus queue full for '%s', dropping event", event_type)

    async def apublish(self, event_type: str, payload: dict) -> None:
        """Async publish — awaits if any subscriber queue is full."""
        for queue in self._queues[event_type]:
            await queue.put(payload)

    # ── Subscribers ─────────────────────────────────────────────────────────

    async def subscribe(
        self, event_type: str, maxsize: int = 2000
    ) -> AsyncIterator[dict]:
        """
        Async generator — yields events as they arrive.
        Automatically unregisters on generator teardown.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues[event_type].append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            try:
                self._queues[event_type].remove(queue)
            except ValueError:
                pass
