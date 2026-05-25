"""
WebSocket Connection Manager
Topic-based pub/sub: clients subscribe to "SYMBOL:TIMEFRAME" topics.
Handles dead connections silently.
"""

import asyncio
from collections import defaultdict
from typing import Dict, Set
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        # topic → set of active WebSocket connections
        self._topics: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, topic: str) -> None:
        await websocket.accept()
        async with self._lock:
            self._topics[topic].add(websocket)
        logger.info(
            "WS client connected  topic=%s  total=%d",
            topic,
            len(self._topics[topic]),
        )

    def disconnect(self, websocket: WebSocket, topic: str) -> None:
        self._topics[topic].discard(websocket)
        logger.info("WS client disconnected  topic=%s", topic)

    async def broadcast_to_topic(self, topic: str, message: str) -> None:
        """Push a text message to every client on a topic; prune dead sockets."""
        dead: Set[WebSocket] = set()
        for ws in list(self._topics.get(topic, set())):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._topics[topic].discard(ws)

    async def send_personal(self, websocket: WebSocket, message: str) -> None:
        try:
            await websocket.send_text(message)
        except Exception as exc:
            logger.debug("Personal send failed: %s", exc)

    def subscriber_count(self, topic: str) -> int:
        return len(self._topics.get(topic, set()))

    def all_topics(self) -> list:
        return [t for t, s in self._topics.items() if s]
