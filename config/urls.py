"""Root URL configuration.

A global `/api` prefix mirrors the NestJS backend (setGlobalPrefix('api')) so the
frontend's existing EDIFY_API_URL contract keeps working unchanged. The health
probe lives at the prefix root; everything else hangs off `api/`.

Routes have NO trailing slash (matching NestJS: /api/schools, /api/auth/login).
APPEND_SLASH is disabled in settings. Each module's urls define leaves WITHOUT a
trailing slash; the `api(...)` helper registers both the bare and slashed prefix
so `/api/schools` and `/api/schools/proposals` both resolve.
"""

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, JsonResponse
from django.urls import include, path


def _health(request: HttpRequest) -> JsonResponse:
    """Public liveness probe: `{status:"ok", db:"up|down"}`."""
    from django.db import connections
    from django.db.utils import OperationalError

    db = "up"
    try:
        connections["default"].cursor().execute("SELECT 1").fetchone()
    except OperationalError:
        db = "down"
    return JsonResponse(
        {"status": "ok" if db == "up" else "degraded", "db": db},
        status=200 if db == "up" else 503,
    )


def api(prefix: str, url_module: str) -> list:
    """Register a module's urls at an /api prefix, accepting both the bare
    prefix (e.g. /api/schools) and the slashed form (/api/schools/...).

    NestJS routes have no trailing slash, so the bare form must match for the
    collection root. The slashed form is required for sub-routes (Django's
    include concatenates prefix + leaf)."""
    return [
        path(f"api/{prefix}", include(url_module)),
        path(f"api/{prefix}/", include(url_module)),
    ]


# API namespace wiring is added incrementally as each module lands.
urlpatterns = [
    path("admin/", admin.site.urls),
    # Health probe — public, DB ping. Matches NestJS GET /api/health.
    path("api/health", _health, name="health"),
    path("api/health/", _health),
    # Auth — public login/refresh/reset + JWT-gated /me.
    *api("auth", "apps.accounts.urls"),
    # Geography — cascading admin-boundary reads.
    *api("geography", "apps.geography.urls"),
    # Schools — the source-of-truth directory.
    *api("schools", "apps.schools.urls"),
    # Upload batches — file-upload audit (schools + SSA).
    *api("uploads", "apps.schools.upload_urls"),
    # Clusters — school grouping by sub-county.
    *api("clusters", "apps.clusters.urls"),
    # SSA — School Self-Assessment.
    *api("ssa", "apps.ssa.urls"),
    # Activities — the 21-state field-work lifecycle.
    *api("activities", "apps.activities.urls"),
    # Budget — the cost spine.
    *api("budget", "apps.budget.urls"),
    # Direct costing preview
    *api("costing", "apps.budget.costing_urls"),
    # Budgets — program + admin aggregation by period (monthly/quarterly/fy).
    *api("budgets", "apps.budget.budgets_urls"),
    # Partners — partner-org directory + self-service.
    *api("partners", "apps.partners.urls"),
    # Assignment — capacity + valid options.
    *api("assignment", "apps.assignment.urls"),
    # Filters — shared filter-bar options + counts.
    *api("filters", "apps.filters.urls"),
    # Search — global search.
    *api("search", "apps.search.urls"),
    # System health — org-wide health counts.
    *api("system-health", "apps.system_health.urls"),
    # Security — data-protection posture (SYSTEM_ADMIN).
    *api("security", "apps.security.urls"),
    # My-plan — the caller's own plan feed.
    *api("my-plan", "apps.my_plan.urls"),
    # HR — staff roster (PII-gated) + leave.
    *api("hr", "apps.hr.urls"),
    # Staff — roster + supervisor assignment (CD/HR/Admin).
    *api("staff", "apps.accounts.staff_urls"),
    # Debriefs — daily field debriefs.
    *api("debriefs", "apps.debriefs.urls"),
    # Targets — CD/IA annual commitments.
    *api("targets", "apps.targets.urls"),
    # Performance — backend-driven staff performance (My/Team/Country/HR targets).
    *api("performance", "apps.targets.performance_urls"),
    # Reports — saved/generated reports.
    *api("reports", "apps.reports.urls"),
    # Flags — CD→PL flag handoff.
    *api("flags", "apps.flags.urls"),
    # PL review queue.
    path("api/pl/review-queue", include("apps.pl_review.urls")),
    path("api/pl/review-queue/", include("apps.pl_review.urls")),
    # Command center — recommendation-led home feed + alerts.
    *api("command-center", "apps.command_center.urls"),
    # Admin users — account provisioning.
    *api("admin/users", "apps.admin_users.urls"),
    # Staff-setup candidates — admin resolution of uploaded staff names.
    *api("staff-candidates", "apps.staff_setup.urls"),
    # Evidence — file pipeline.
    *api("evidence", "apps.evidence.urls"),
    # Special projects.
    *api("special-projects", "apps.projects.urls"),
    # Messaging — in-app threads.
    *api("messages", "apps.messaging.urls"),
    # Notifications — per-user rail.
    *api("notifications", "apps.notifications.urls"),
    # Planning — plan authoring + scheduling + lifecycle.
    *api("planning", "apps.planning.urls"),
    # Fund requests — the Budget → Fund Request approval chain.
    *api("fund-requests", "apps.fund_requests.urls"),
    # Budget lines direct access
    *api("budget-lines", "apps.budget.budget_lines_urls"),
    # Core schools — the Core/Champion pipeline.
    *api("core", "apps.core_schools.urls"),
    # Monthly work-plan budget — CD→RVP routing.
    *api("monthly-work-plan-budget", "apps.monthly_work_plan.urls"),
    # Analytics — role-scoped summaries.
    *api("analytics", "apps.analytics.urls"),
    # Leadership Decision Engine — recommends; leadership decides.
    path("api/leadership/decision-engine", include("apps.leadership.urls")),
    path("api/leadership/decision-engine/", include("apps.leadership.urls")),
    # Budget Intelligence — the financial decision engine.
    *api("budget-intelligence", "apps.budget_intelligence.urls"),
    # Realtime — SSE live stream.
    *api("realtime", "apps.realtime.urls"),
    # Frontend Pages
    path("", include("apps.frontend.urls")),
]


# drf-spectacular OpenAPI at /api/docs (non-production only) — wired once the
# feature modules are in place.
if not settings.IS_PRODUCTION:
    try:
        from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
    except ImportError:  # pragma: no cover - spectacular may be absent early on
        pass
    else:
        urlpatterns += [
            path("api/docs/schema/", SpectacularAPIView.as_view(), name="schema"),
            path(
                "api/docs/",
                SpectacularSwaggerView.as_view(url_name="schema"),
                name="swagger-ui",
            ),
        ]
