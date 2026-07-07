"""
DRF exception handler + business exceptions.

The handler renders the NestJS-style envelope `{statusCode, correlationId,
message}`. Business 4xx keep their messages; 5xx are generic. DRF exceptions
raised in views are handled here, while truly uncaught exceptions fall through
to AllExceptionsMiddleware.
"""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import APIException

from .request_context import get_correlation_id


def edify_exception_handler(exc: Exception, context: dict):
    # Import lazily to avoid a circular import at DRF settings load time.
    from rest_framework.views import exception_handler as drf_default_handler

    response = drf_default_handler(exc, context)
    if response is None:
        # Fall through to the catch-all middleware for non-DRF errors.
        return None

    correlation_id = get_correlation_id()
    detail: Any = getattr(exc, "detail", str(exc))
    if isinstance(detail, (list, dict)):
        message = detail
    else:
        message = str(detail)

    response.data = {
        "statusCode": response.status_code,
        "correlationId": correlation_id,
        "message": message,
    }
    return response


# ── Business exceptions mirroring NestJS HttpException subclasses ────────────
class EdifyAPIException(APIException):
    """Base for intentional, client-safe errors."""

    status_code = 400
    default_detail = "Bad request."


class BadRequest(EdifyAPIException):
    status_code = 400
    default_detail = "Bad request."


class ConflictError(EdifyAPIException):
    status_code = 409
    default_detail = "Conflict."


class NotFoundError(EdifyAPIException):
    status_code = 404
    default_detail = "Not found."


class Forbidden(EdifyAPIException):
    status_code = 403
    default_detail = "You don't have permission to do that."


class Unauthorized(EdifyAPIException):
    status_code = 401
    default_detail = "Authentication required."


class ValidationError(EdifyAPIException):
    status_code = 422
    default_detail = "Validation failed."


__all__ = [
    "edify_exception_handler",
    "EdifyAPIException",
    "BadRequest",
    "ConflictError",
    "NotFoundError",
    "Forbidden",
    "Unauthorized",
    "ValidationError",
]
