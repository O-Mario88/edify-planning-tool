"""
Realtime SSE endpoint — GET /api/realtime/stream.

Emits `connected` immediately, then scoped events (this user's notifications +
domain refreshes), with a 25s heartbeat. Accepts a Bearer token. The client's
EventSource opens this; on each domain event it dispatches a window event +
debounces a router.refresh() (FE concern).
"""

from __future__ import annotations

import asyncio
import json
import queue
import time

from django.http import StreamingHttpResponse

from .bus import bus

#: How often the loop checks the bus, and how long a quiet stream waits before
#: sending a keep-alive. Polling is cheap; the sleep is what frees the loop.
_POLL_SECONDS = 0.5
_HEARTBEAT_SECONDS = 25.0


def _sse(data: dict) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode("utf-8")


def stream(request):
    """The SSE stream. Authenticates via session OR the JWT in the Authorization header."""
    user_id = None
    if hasattr(request, "user") and request.user and request.user.is_authenticated:
        user_id = request.user.id
    else:
        from apps.accounts.jwt import JwtAuthentication

        # Authenticate manually (StreamingHttpResponse bypasses DRF dispatch).
        auth = JwtAuthentication()
        try:
            user_auth = auth.authenticate(request)
            if user_auth is not None:
                principal = user_auth[0]
                user_id = principal.user_id
        except Exception:
            pass

    if not user_id:
        response = StreamingHttpResponse(
            ["data: unauthorized\n\n"], content_type="text/event-stream"
        )
        response.status_code = 401
        return response

    # SSE streams are long-lived and run on a loop without doing DB operations.
    # We must close the Django database connection here so it is not held open
    # indefinitely, which would otherwise exhaust the Postgres connection pool.
    from django.db import connections

    connections.close_all()

    async def event_stream():
        """Async generator — required, not stylistic.

        This was a *synchronous* infinite generator. Under ASGI (production
        runs Daphne) Django cannot `async for` a sync iterator, so it falls back
        to `await sync_to_async(list)(streaming_content)` — it tries to
        materialise an endless stream into a list before sending a single byte.
        The client received the 200 and its headers and then nothing, forever.

        Worse, because the request was parked inside that blocking call, client
        disconnect could not interrupt it: the `finally` never ran, so every
        connection permanently leaked one executor thread and one 256-slot
        queue. The endpoint has no rate limit, so opening streams in a loop was
        enough to exhaust the process.

        Subscribing before the first yield closes a smaller race — an event
        published between "connected" and `subscribe()` used to be dropped.
        """
        q = bus.subscribe(user_id)
        try:
            yield _sse({"type": "connected", "at": _now_iso()})
            last_beat = time.monotonic()
            while True:
                drained = False
                while True:
                    try:
                        event = q.get_nowait()
                    except queue.Empty:
                        break
                    drained = True
                    yield _sse(event)
                now = time.monotonic()
                if drained:
                    last_beat = now
                elif now - last_beat >= _HEARTBEAT_SECONDS:
                    last_beat = now
                    yield _sse({"type": "heartbeat", "at": _now_iso()})
                # Yield to the event loop. The bus is a thread-safe sync queue
                # written from ordinary workflow code, so it is polled rather
                # than awaited; sleeping here is what keeps the loop free and
                # keeps cancellation working.
                await asyncio.sleep(_POLL_SECONDS)
        finally:
            bus.unsubscribe(user_id, q)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # disable nginx buffering
    response["Connection"] = "keep-alive"
    return response


def _now_iso() -> str:
    from django.utils import timezone

    return timezone.now().isoformat()
