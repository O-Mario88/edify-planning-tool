"""
Per-request provenance via contextvars.

A faithful port of the NestJS `AsyncLocalStorage` request context: every
request opens a scope carrying `ip_address`, `user_agent`, `correlation_id`.
The singleton audit logger reads provenance from it without threading the
context through dozens of service call sites.

Honors an inbound `x-correlation-id` (cross-service tracing) or mints one,
and echoes it on the response so logs + the error envelope share it.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class RequestContext:
    ip_address: Optional[str]
    user_agent: Optional[str]
    correlation_id: str


_current: ContextVar[Optional[RequestContext]] = ContextVar(
    "edify_request_context", default=None
)


def get_request_context() -> Optional[RequestContext]:
    return _current.get()


def get_correlation_id() -> str:
    ctx = _current.get()
    return ctx.correlation_id if ctx else "unknown"


def set_request_context(ctx: RequestContext) -> None:
    _current.set(ctx)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


__all__ = [
    "RequestContext",
    "get_request_context",
    "get_correlation_id",
    "set_request_context",
    "new_correlation_id",
]
