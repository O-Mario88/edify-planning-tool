"""
Cross-cutting middleware.

`RequestContextMiddleware` opens the per-request provenance scope (mirrors
NestJS `requestContextMiddleware`); `AllExceptionsMiddleware` renders the
generic error envelope without leaking internals (mirrors `AllExceptionsFilter`).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

from .request_context import (
    RequestContext,
    new_correlation_id,
    set_request_context,
    get_correlation_id,
)

logger = logging.getLogger("edify.exceptions")


class RequestContextMiddleware:
    """First-in middleware: open a contextvars scope for the request so the
    audit logger can stamp ip/user-agent/correlationId onto every row."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        correlation_id = request.headers.get("x-correlation-id") or new_correlation_id()
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = (
            forwarded.split(",")[0].strip()
            if forwarded
            else request.META.get("REMOTE_ADDR")
        )
        ctx = RequestContext(
            ip_address=ip,
            user_agent=request.headers.get("user-agent"),
            correlation_id=correlation_id,
        )
        set_request_context(ctx)

        response = self.get_response(request)
        # Echo the correlation id so client + logs tie together.
        response["x-correlation-id"] = correlation_id
        return response


class AllExceptionsMiddleware:
    """Catch-all envelope: clients never see stack traces, DB errors, or
    internal paths. Business 4xx keep their (intentional, safe) messages;
    5xx return a generic message. Every response carries the correlationId.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(
        self, request: HttpRequest, exception: Exception
    ) -> JsonResponse | None:
        from rest_framework.exceptions import APIException

        correlation_id = get_correlation_id()

        from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
        from django.http import Http404 as DjangoHttp404

        if isinstance(exception, DjangoPermissionDenied):
            logger.debug(
                "[%s] %s %s -> 403 : %s",
                correlation_id,
                request.method,
                request.path,
                str(exception),
            )
            # `/api/*` is the DRF/JSON contract (mirrors NestJS) — keep the
            # JSON envelope there. Everything else is a plain server-rendered
            # page (e.g. get_scoped_object_or_404 raising inside a Django
            # view) — render the same flash-and-redirect / 403 page contract
            # require_page_permission() already uses, instead of surfacing a
            # raw JSON blob on a security boundary.
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {
                        "statusCode": 403,
                        "correlationId": correlation_id,
                        "message": str(exception),
                    },
                    status=403,
                )

            from apps.core.permissions import render_access_denied

            return render_access_denied(request, str(exception))

        if isinstance(exception, DjangoHttp404):
            logger.debug(
                "[%s] %s %s -> 404 : %s",
                correlation_id,
                request.method,
                request.path,
                str(exception),
            )
            return JsonResponse(
                {
                    "statusCode": 404,
                    "correlationId": correlation_id,
                    "message": str(exception),
                },
                status=404,
            )

        # DRF APIException is the "business" error family — preserve its status
        # and detail (mirrors NestJS HttpException handling).
        if isinstance(exception, APIException):
            status = exception.status_code
            detail = exception.detail
            payload_detail: Any
            if isinstance(detail, (list, dict)):
                payload_detail = detail
            else:
                payload_detail = str(detail)
            logger.debug(
                "[%s] %s %s -> %s : %s",
                correlation_id,
                request.method,
                request.path,
                status,
                str(detail),
            )
            return JsonResponse(
                {
                    "statusCode": status,
                    "correlationId": correlation_id,
                    "message": payload_detail,
                },
                status=status,
            )

        # Unknown/5xx — never leak internals.
        status = 500
        # The client only receives a safe generic envelope, but retain the
        # correlation, request shape and exception class in the immutable
        # audit trail. This gives support a usable lead when an exception
        # occurs before a feature-level audit event can be written.
        from apps.audit.services import log as audit_log

        user = getattr(request, "user", None)
        actor_id = (
            str(user.id)
            if getattr(user, "is_authenticated", False) and getattr(user, "id", None)
            else None
        )
        audit_log(
            action="request_failed",
            subject_kind="Request",
            subject_id=request.path[:30] or "/",
            actor_id=actor_id,
            actor_role=getattr(user, "active_role", None) if actor_id else None,
            success=False,
            reason=f"Unhandled {type(exception).__name__}",
            payload={
                "method": request.method,
                "path": request.path,
                "exception_type": type(exception).__name__,
            },
        )
        logger.exception(
            "[%s] %s %s -> 500 : %s",
            correlation_id,
            request.method,
            request.path,
            exception,
        )
        return JsonResponse(
            {
                "statusCode": status,
                "correlationId": correlation_id,
                "message": "We could not complete that action. Please try again.",
            },
            status=status,
        )


class ContentSecurityPolicyMiddleware:
    """A second line of defence behind output escaping.

    Escaping is the primary control and this does not replace it. What a policy
    adds is a floor: if an injection does land, it decides what the injected
    markup is allowed to *do*. Without one, injected script runs with the same
    authority as the application's own.

    Two things about this policy are worth stating plainly, because both look
    like weaknesses until you know why:

    `'unsafe-eval'` is required by Alpine.js, which compiles the expressions in
    `x-data` and `@click` with `new Function()`. Alpine ships a CSP-friendly
    build, but it accepts a restricted expression syntax that every component
    here would have to be rewritten into. Dropping it is a real piece of work,
    not a settings change.

    `'unsafe-inline'` in style-src covers the inline `style="--token: value"`
    attributes that carry live data into CSS custom properties — a chart's
    computed width, a gauge's size. Those are values, not code.

    Even with both, the policy still blocks the shapes that matter most: a
    script element sourced from an attacker's host, a rewritten <base> that
    silently repoints every relative URL, a form re-posted to another origin,
    plugin content, and framing by anyone at all.
    """

    # Every external origin the application actually loads, and nothing else.
    # Fonts and the two CDN libraries are the whole list; the map tiles are
    # images. Adding an origin here should be a deliberate, reviewed edit.
    POLICY = "; ".join(
        (
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://unpkg.com https://cdn.jsdelivr.net",
            # unpkg is here for leaflet.css on the school map, not only for
            # scripts — a stylesheet origin missing from this list fails
            # silently as an unstyled component rather than a visible error.
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
            "https://cdn.jsdelivr.net https://unpkg.com",
            "font-src 'self' data: https://fonts.gstatic.com",
            "img-src 'self' data: blob: https://tile.openstreetmap.org",
            "connect-src 'self'",
            # No plugins, no <base> rewriting, no framing, and forms may only
            # post back to this origin.
            "object-src 'none'",
            "base-uri 'self'",
            "frame-ancestors 'none'",
            "form-action 'self'",
        )
    )

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        # Never overwrite a policy a view set deliberately for itself.
        response.setdefault("Content-Security-Policy", self.POLICY)
        return response
