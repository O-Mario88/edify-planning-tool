"""
In-process realtime event bus — a faithful port of the NestJS RxJS Subject
pub/sub. One stream per user; the SSE controller subscribes, the DomainEvent
seam publishes. Single-process; Redis pub/sub noted as the future swap (only
this class changes, not its callers).
"""

from __future__ import annotations

import queue
import threading
from collections import defaultdict
from typing import Any


class _EventBus:
    """Per-user queue-based event bus. Each connected user gets a queue; events
    are pushed to it; the SSE view drains it. A 25s heartbeat keeps the
    connection alive."""

    def __init__(self) -> None:
        self._queues: dict[str, list[queue.Queue]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, user_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._queues[user_id].append(q)
        return q

    def unsubscribe(self, user_id: str, q: queue.Queue) -> None:
        with self._lock:
            if q in self._queues.get(user_id, []):
                self._queues[user_id].remove(q)
                if not self._queues[user_id]:
                    self._queues.pop(user_id, None)

    def publish(self, user_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._queues.get(user_id, []))
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                # Drop oldest to make room — never block the publisher.
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass

    def publish_many(self, user_ids, event: dict[str, Any]) -> None:
        for uid in dict.fromkeys(filter(None, user_ids)):
            self.publish(uid, event)

    def connection_count(self) -> int:
        with self._lock:
            return sum(len(qs) for qs in self._queues.values())


bus = _EventBus()

__all__ = ["bus"]
