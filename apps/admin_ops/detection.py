"""Turn platform failures into actionable Admin work, not log lines.

A 500 in a log file is invisible; an incident with an owner, a severity, a
next action and a deep link is work. This module is the detection edge:

  * server errors (5xx) and permission drift (unexpected 403)
  * broken routes (404 on a registered application link)
  * slow responses breaching the configured SLO
  * client-reported defects — dead buttons, JS exceptions, failed HTMX swaps
  * background-job failure and overdue detection

Everything funnels into ``SystemIncidentService.report``, which deduplicates on
a stable signature, so one recurring defect stays one incident however often it
fires.
"""

from __future__ import annotations

import time

from django.conf import settings

from apps.admin_ops.models import Severity, WorkItemCategory
from apps.admin_ops.services import SystemIncidentService

# Response time above which a request is treated as an SLO breach (§16).
DEFAULT_SLO_MS = 3000
# A single slow request is noise; a route that is repeatedly slow is a defect.
SLOW_OCCURRENCES_BEFORE_INCIDENT = 3

_slow_counts: dict[str, int] = {}


def _environment() -> str:
    return getattr(settings, "EDIFY_ENVIRONMENT", "local")


def _slo_ms() -> int:
    return int(getattr(settings, "ADMIN_OPS_SLO_MS", DEFAULT_SLO_MS))


def _enabled() -> bool:
    """Detection writes incidents, so it is a setting, not a hard-wired edge.

    Default on. The test settings turn it off, because a suite that exercises
    hundreds of deliberate refusals and error paths would otherwise spend its
    time recording that the application refused exactly as designed. The
    detection functions themselves are tested directly.
    """
    return bool(getattr(settings, "ADMIN_OPS_DETECTION_ENABLED", True))


def _is_permission_drift(request) -> bool:
    """A 403 is only a defect when the role SHOULD have reached the page.

    Refusing a role that was never authorised is the permission system working.
    Treating every 403 as an incident was the wrong signal: it would have
    reported the guard rails, not the drift. Drift is the narrow case where
    ``PAGE_PERMISSIONS`` says yes and the request was refused anyway.
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return False
    try:
        from django.urls import resolve

        from apps.core.navigation import PAGE_PERMISSIONS, get_user_role_slug

        # The page key comes from the guard decorator, which publishes it as
        # `page_permission`. Resolving it from the URL *name* instead would
        # have made this detector silently blind: /planning resolves to the
        # url_name "planning_dashboard", which is not a PAGE_PERMISSIONS key,
        # so every lookup would miss and no drift would ever be reported.
        view = resolve(request.path).func
        page_key = getattr(view, "page_permission", None)
        if not page_key:
            return False
        allowed = PAGE_PERMISSIONS.get(page_key)
        if not allowed:
            return False
        return get_user_role_slug(user) in allowed
    except Exception:
        return False


def _is_application_route(path: str) -> bool:
    """A 404 on a real application link is a defect; on a random URL it is not."""
    if path.startswith(("/static/", "/media/", "/favicon", "/.well-known")):
        return False
    from django.urls import Resolver404, resolve

    try:
        resolve(path)
    except Resolver404:
        return False
    return True


class PlatformFailureDetectionMiddleware:
    """Observe every response; raise an incident for the ones that matter."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _enabled():
            return self.get_response(request)
        started = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        try:
            self._inspect(request, response, elapsed_ms)
        except Exception:  # detection must never break the request it observes
            pass
        return response

    def _inspect(self, request, response, elapsed_ms: int) -> None:
        path = request.path
        status = response.status_code
        request_id = getattr(request, "correlation_id", "") or request.headers.get(
            "X-Request-ID", ""
        )

        if status >= 500:
            SystemIncidentService.report(
                title=f"Server error on {path}",
                category=WorkItemCategory.BACKEND_DEFECT,
                severity=Severity.CRITICAL if status == 500 else Severity.HIGH,
                route=path,
                component="backend",
                error=f"http_{status}",
                environment=_environment(),
                request_id=request_id,
                detail={"method": request.method, "status": status},
            )
            return

        if status == 404 and _is_application_route(path):
            SystemIncidentService.report(
                title=f"Registered route returns 404: {path}",
                category=WorkItemCategory.ROUTE_DEFECT,
                severity=Severity.HIGH,
                route=path,
                component="routing",
                error="http_404_registered_route",
                environment=_environment(),
                request_id=request_id,
            )
            return

        if status == 403 and _is_permission_drift(request):
            SystemIncidentService.report(
                title=f"Permission drift on {path}",
                category=WorkItemCategory.CONFIGURATION,
                severity=Severity.MEDIUM,
                route=path,
                component="permissions",
                error="http_403_permission_drift",
                environment=_environment(),
                request_id=request_id,
                detail={"role": getattr(request.user, "active_role", "")},
            )
            return

        if elapsed_ms > _slo_ms() and request.method in ("GET", "POST"):
            key = f"{request.method}:{path}"
            _slow_counts[key] = _slow_counts.get(key, 0) + 1
            if _slow_counts[key] >= SLOW_OCCURRENCES_BEFORE_INCIDENT:
                _slow_counts[key] = 0
                SystemIncidentService.report(
                    title=f"{path} exceeds the {_slo_ms()}ms SLO",
                    category=WorkItemCategory.PERFORMANCE,
                    severity=Severity.HIGH,
                    route=path,
                    component="performance",
                    error="slo_breach",
                    environment=_environment(),
                    request_id=request_id,
                    detail={"elapsed_ms": elapsed_ms, "slo_ms": _slo_ms()},
                )


# ── Client-reported defects (§15) ────────────────────────────────────────────

CLIENT_DEFECT_KINDS = {
    "dead_button": (WorkItemCategory.FRONTEND_DEFECT, Severity.HIGH, "Dead button"),
    "js_exception": (
        WorkItemCategory.FRONTEND_DEFECT,
        Severity.HIGH,
        "JavaScript exception",
    ),
    "htmx_failure": (
        WorkItemCategory.FRONTEND_DEFECT,
        Severity.HIGH,
        "HTMX request failed",
    ),
    "frozen_screen": (
        WorkItemCategory.PERFORMANCE,
        Severity.HIGH,
        "Screen stopped responding",
    ),
    "slow_page": (WorkItemCategory.PERFORMANCE, Severity.MEDIUM, "Slow page"),
}


def report_client_defect(
    *, kind: str, route: str, component: str, detail: dict, request_id: str = ""
):
    """Intake for browser-detected defects.

    Deliberately narrow: kind must be one we recognise, and only the named
    diagnostic fields are stored. A browser payload is untrusted input, so it
    never reaches the incident record verbatim.
    """
    if kind not in CLIENT_DEFECT_KINDS:
        return None
    category, severity, label = CLIENT_DEFECT_KINDS[kind]
    safe_detail = {
        k: str(detail.get(k, ""))[:500]
        for k in (
            "component",
            "message",
            "target",
            "status",
            "elapsed_ms",
            "user_agent",
        )
        if detail.get(k) is not None
    }
    return SystemIncidentService.report(
        title=f"{label} on {route or 'an unknown page'}",
        category=category,
        severity=severity,
        route=route[:255],
        component=component[:128] or "frontend",
        error=f"client:{kind}:{safe_detail.get('component', component)}",
        environment=_environment(),
        request_id=request_id,
        detail=safe_detail,
    )


# ── Background jobs (§13) ────────────────────────────────────────────────────


def report_job_failure(job_name: str, error: str, run_id: str = ""):
    return SystemIncidentService.report(
        title=f"Background job failed: {job_name}",
        category=WorkItemCategory.JOB_FAILURE,
        severity=Severity.HIGH,
        route=f"/system-health/jobs/{job_name}",
        component=job_name,
        error=f"job_failed:{job_name}",
        environment=_environment(),
        request_id=run_id,
        detail={"error": str(error)[:500]},
    )


def report_job_overdue(job_name: str, minutes_late: int):
    return SystemIncidentService.report(
        title=f"Background job overdue: {job_name}",
        category=WorkItemCategory.JOB_FAILURE,
        severity=Severity.HIGH if minutes_late > 120 else Severity.MEDIUM,
        route=f"/system-health/jobs/{job_name}",
        component=job_name,
        error=f"job_overdue:{job_name}",
        environment=_environment(),
        detail={"minutes_late": minutes_late},
    )
