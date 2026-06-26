"""
Realtime SSE endpoint — GET /api/realtime/stream.

Emits `connected` immediately, then scoped events (this user's notifications +
domain refreshes), with a 25s heartbeat. Accepts a Bearer token. The client's
EventSource opens this; on each domain event it dispatches a window event +
debounces a router.refresh() (FE concern).
"""
from __future__ import annotations

import json
import time

from django.http import StreamingHttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from .bus import bus


def _sse(data: dict) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode("utf-8")


def stream(request):
    """The SSE stream. Authenticates via the JWT in the Authorization header."""
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory
    from apps.accounts.jwt import JwtAuthentication

    # Authenticate manually (StreamingHttpResponse bypasses DRF dispatch).
    auth = JwtAuthentication()
    user_auth = auth.authenticate(request)
    if user_auth is None:
        response = StreamingHttpResponse(["data: unauthorized\n\n"], content_type="text/event-stream")
        response.status_code = 401
        return response
    principal = user_auth[0]
    user_id = principal.user_id

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
