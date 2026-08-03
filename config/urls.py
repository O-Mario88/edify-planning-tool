"""Root URL configuration.

A global `/api` prefix mirrors the NestJS backend (setGlobalPrefix('api')) so the
frontend's existing EDIFY_API_URL contract keeps working unchanged. The health
probe lives at the prefix root; everything else hangs off `api/`.

Routes have NO trailing slash (matching NestJS: /api/schools, /api/auth/login).
APPEND_SLASH is disabled in settings. Each module's urls define leaves WITHOUT a
trailing slash; the `api(...)` helper uses one boundary-aware matcher so
`/api/schools` and `/api/schools/proposals` both resolve without also creating
the malformed shadow route `/api/schoolsproposals`.
"""

import re

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, JsonResponse
from django.urls import include, path, re_path
from django.views.generic import RedirectView


def _liveness(request: HttpRequest) -> JsonResponse:
    """Is this process alive? Nothing else.

    Deliberately touches no dependency. A liveness probe answers one question,
    and the orchestrator's response to a failure is to KILL AND RESTART the
    container — so a probe that checks the database turns a database blip into
    a restart of every instance, destroying the capacity that would otherwise
    have served traffic the moment the database came back. Readiness is the
    probe that is allowed to care about dependencies, because its failure only
    takes an instance out of rotation.
    """
    return JsonResponse({"status": "ok"}, status=200)


def _build(request: HttpRequest) -> JsonResponse:
    """What artifact is serving this request?

    Unauthenticated on purpose. The question "is production running the build
    we shipped?" has to be answerable from outside — by CI, by a deploy gate,
    by whoever is looking at a page that seems wrong — and a check that needs
    a session is a check nobody runs. Nothing here is a secret: a commit SHA,
    a build timestamp, a digest of the public static manifest, and the hashed
    filenames of assets any visitor already downloads.

    Cache-Control is explicit. A cached answer to "which build is this?" is
    worse than no answer, because it is confidently wrong for exactly as long
    as the cache lives.
    """
    from apps.core.build_info import asset_hash, build_info

    payload = dict(build_info())
    payload["assets"] = {
        name: asset_hash(name)
        for name in (
            "css/main.css",
            "css/design-system.css",
            "css/components.css",
            "css/fonts.css",
        )
    }
    response = JsonResponse(payload, status=200)
    response["Cache-Control"] = "no-store, max-age=0"
    return response


def _readiness(request: HttpRequest) -> JsonResponse:
    """Can this process safely serve traffic right now?

    Cheap by design: `SELECT 1`, not a survey of the schema. A readiness probe
    runs every few seconds on every instance, so anything expensive here is a
    load generator pointed at the dependency it is meant to be protecting.
    """
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
    """Register one boundary-aware API prefix.

    The old pair of ``path()`` includes made both intended forms work, but the
    bare include also concatenated every child without a separator. That made
    `/api/schoolsbulk` a real endpoint and duplicated the entire OpenAPI
    surface. One regex consumes either a slash or the end of the string.
    """
    if not re.fullmatch(r"[a-z0-9/-]+", prefix):
        raise ValueError(f"Unsafe API prefix: {prefix!r}")
    return [
        re_path(
            rf"^api/{prefix}(?:/|$)",
            include(url_module),
        )
    ]


# API namespace wiring is added incrementally as each module lands.
urlpatterns = [
    path("admin/", admin.site.urls),
    # Health probes, split by what a failure should make an orchestrator do.
    # /api/health keeps its existing dependency-checking behaviour because
    # deploy gates already point at it; /api/health/live is the one a container
    # HEALTHCHECK should use, since that failure means "restart me".
    path("api/health", _readiness, name="health"),
    path("api/health/", _readiness),
    path("api/health/live", _liveness, name="health_live"),
    path("api/health/ready", _readiness, name="health_ready"),
    # Release provenance. See _build: this is the endpoint that makes
    # "is the approved design actually deployed?" a question with an answer.
    path("api/health/build", _build, name="health_build"),
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
    # Governed Activity Catalogue master data + SSA-led suggestions.
    *api("activity-catalogue", "apps.activity_catalogue.urls"),
    # Budget — the cost spine.
    *api("budget", "apps.budget.urls"),
    # Direct costing preview
    *api("costing", "apps.budget.costing_urls"),
    # Budgets — program + admin aggregation by period (monthly/quarterly/fy).
    *api("budgets", "apps.budget.budgets_urls"),
    # Partners — partner-org directory + self-service.
    *api("partners", "apps.partners.urls"),
    *api("partner-assignments", "apps.partners.assignment_urls"),
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
    *api("pl/review-queue", "apps.pl_review.urls"),
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
    *api("projects", "apps.projects.urls"),
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
    *api("leadership/decision-engine", "apps.leadership.urls"),
    # Budget Intelligence — the financial decision engine.
    *api("budget-intelligence", "apps.budget_intelligence.urls"),
    # Realtime — SSE live stream.
    *api("realtime", "apps.realtime.urls"),
    # Frontend Pages
    # Platform operations + the platform-wide support intake. Ahead of the
    # frontend catch-all so /support resolves here rather than to a
    # frontend pattern.
    path("", include("apps.admin_ops.urls")),
    path("", include("apps.documents.urls")),
    # /lander never belonged to this application. It was GoDaddy's parked-domain
    # page, reached because the apex A record pointed at GoDaddy Forwarding
    # rather than at the origin (INC-2026-08-03-01). Once the apex resolves here
    # the path is ours, and the people who arrive on it are following a bookmark
    # or a cached link from the outage — so it lands them on the real root
    # instead of a 404. Ahead of the frontend catch-all, which would otherwise
    # claim it.
    re_path(
        r"^lander/?$",
        RedirectView.as_view(url="/", permanent=True, query_string=True),
        name="lander-legacy",
    ),
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
