"""
Realtime SSE endpoint — GET /api/realtime/stream.

Emits `connected` immediately, then scoped events (this user's notifications +
domain refreshes), with a 25s heartbeat. Accepts a Bearer token. The client's
EventSource opens this; on each domain event it dispatches a window event +
debounces a router.refresh() (FE concern).
"""
from __future__ import annotations

import json

from django.http import StreamingHttpResponse

from .bus import bus


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
        response = StreamingHttpResponse(["data: unauthorized\n\n"], content_type="text/event-stream")
        response.status_code = 401
        return response

    # SSE streams are long-lived and run on a loop without doing DB operations.
    # We must close the Django database connection here so it is not held open
    # indefinitely, which would otherwise exhaust the Postgres connection pool.
    from django.db import connections
    connections.close_all()

    def event_stream():
        yield _sse({"type": "connected", "at": _now_iso()})
        q = bus.subscribe(user_id)
        try:
            while True:
                try:
                    event = q.get(timeout=25)
                    yield _sse(event)
                except Exception:
                    # Heartbeat every 25s.
                    yield _sse({"type": "heartbeat", "at": _now_iso()})
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
