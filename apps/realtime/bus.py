"""Bounded per-user realtime delivery across every web replica.

Each SSE connection owns a small in-process queue for immediate delivery and,
when ``REDIS_URL`` is available, a Redis/Valkey pub-sub subscription for events
created by other processes. The local queue is deliberately retained: a cache
outage may make realtime stale, but it must never make a committed workflow
fail or block a request indefinitely.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from collections import defaultdict
from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

logger = logging.getLogger("edify.realtime")

_CHANNEL_PREFIX = "edify:realtime:user:"
_QUEUE_SIZE = 256
_REDIS_TIMEOUT_SECONDS = 0.5
_REDIS_RETRY_SECONDS = 30.0


class _Subscription:
    """Queue-compatible subscription consumed by the SSE view."""

    def __init__(
        self, *, local: queue.Queue, pubsub, source_id: str, on_transport_error
    ) -> None:
        self.local = local
        self.pubsub = pubsub
        self.source_id = source_id
        self.on_transport_error = on_transport_error

    def get_nowait(self) -> dict[str, Any]:
        try:
            return self.local.get_nowait()
        except queue.Empty:
            pass

        if self.pubsub is not None:
            message = self._shared_message()
            while message:
                if message.get("type") != "message":
                    message = self._shared_message()
                    continue
                try:
                    raw = message.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    envelope = json.loads(raw)
                    # The source process already delivered this event through
                    # its local queue. Redis exists for the other replicas.
                    if envelope.get("source") != self.source_id:
                        event = envelope["event"]
                        if isinstance(event, dict):
                            return event
                except (KeyError, TypeError, ValueError, UnicodeDecodeError):
                    logger.warning("Discarding an invalid realtime pub-sub message")
                message = self._shared_message()
        raise queue.Empty

    def _shared_message(self):
        try:
            return self.pubsub.get_message(ignore_subscribe_messages=True, timeout=0)
        except Exception:  # noqa: BLE001 - retain local delivery after any failed read
            self.on_transport_error("Realtime shared subscription failed")
            self.close()
            self.pubsub = None
            return None

    def close(self) -> None:
        if self.pubsub is not None:
            try:
                self.pubsub.close()
            except Exception:  # noqa: BLE001 - disconnect cleanup is best effort
                logger.debug("Realtime pub-sub cleanup failed", exc_info=True)


class _EventBus:
    """Per-user bounded delivery with an optional shared Redis transport."""

    def __init__(self, *, redis_client=None, source_id: str | None = None) -> None:
        self._queues: dict[str, list[_Subscription]] = defaultdict(list)
        # Re-entrant because lazy client construction can trip the circuit
        # breaker while it already owns the initialisation lock.
        self._lock = threading.RLock()
        self._redis_client = redis_client
        self._redis_url: str | None = None
        self._redis_retry_after = 0.0
        self._source_id = source_id or uuid.uuid4().hex

    def _client(self):
        if self._redis_client is not None:
            return self._redis_client
        if time.monotonic() < self._redis_retry_after:
            return None
        with self._lock:
            if self._redis_client is not None:
                return self._redis_client
            if time.monotonic() < self._redis_retry_after:
                return None
            redis_url = self._redis_url or getattr(settings, "REDIS_URL", None)
            if not redis_url:
                return None
            self._redis_url = redis_url
            try:
                import redis

                self._redis_client = redis.Redis.from_url(
                    redis_url,
                    socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
                    socket_timeout=_REDIS_TIMEOUT_SECONDS,
                )
            except Exception:  # noqa: BLE001 - local delivery remains available
                self._mark_transport_unavailable(
                    "Shared realtime transport unavailable; using this process only"
                )
            return self._redis_client

    def _mark_transport_unavailable(self, message: str) -> None:
        with self._lock:
            already_open = time.monotonic() < self._redis_retry_after
            self._redis_client = None
            self._redis_retry_after = time.monotonic() + _REDIS_RETRY_SECONDS
        if not already_open:
            logger.warning(message, exc_info=True)

    @staticmethod
    def _channel(user_id: str) -> str:
        return f"{_CHANNEL_PREFIX}{user_id}"

    def subscribe(self, user_id: str) -> _Subscription:
        local: queue.Queue = queue.Queue(maxsize=_QUEUE_SIZE)
        pubsub = None
        client = self._client()
        if client is not None:
            try:
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(self._channel(user_id))
            except Exception:  # noqa: BLE001 - local delivery remains available
                self._mark_transport_unavailable(
                    "Realtime subscription could not attach to shared transport"
                )
                if pubsub is not None:
                    try:
                        pubsub.close()
                    except Exception:  # noqa: BLE001
                        pass
                pubsub = None

        subscription = _Subscription(
            local=local,
            pubsub=pubsub,
            source_id=self._source_id,
            on_transport_error=self._mark_transport_unavailable,
        )
        with self._lock:
            self._queues[user_id].append(subscription)
        return subscription

    def unsubscribe(self, user_id: str, subscription: _Subscription) -> None:
        with self._lock:
            if subscription in self._queues.get(user_id, []):
                self._queues[user_id].remove(subscription)
                if not self._queues[user_id]:
                    self._queues.pop(user_id, None)
        subscription.close()

    @staticmethod
    def _put_bounded(target: queue.Queue, event: dict[str, Any]) -> None:
        try:
            target.put_nowait(event)
            return
        except queue.Full:
            pass
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        try:
            target.put_nowait(event)
        except queue.Full:
            pass

    def publish(self, user_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._queues.get(user_id, []))
        for subscription in subscribers:
            self._put_bounded(subscription.local, event)

        client = self._client()
        if client is None:
            return
        try:
            payload = json.dumps(
                {"source": self._source_id, "event": event},
                cls=DjangoJSONEncoder,
                separators=(",", ":"),
            )
            client.publish(self._channel(user_id), payload)
        except Exception:  # noqa: BLE001 - committed work must remain committed
            self._mark_transport_unavailable(
                "Realtime event could not reach other web replicas"
            )

    def publish_many(self, user_ids, event: dict[str, Any]) -> None:
        for uid in dict.fromkeys(filter(None, user_ids)):
            self.publish(uid, event)

    def connection_count(self) -> int:
        with self._lock:
            return sum(len(subscriptions) for subscriptions in self._queues.values())


bus = _EventBus()

__all__ = ["bus"]
