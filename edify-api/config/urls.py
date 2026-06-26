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
    # Clusters — school grouping by sub-county.
    *api("clusters", "apps.clusters.urls"),
    # SSA — School Self-Assessment.
    *api("ssa", "apps.ssa.urls"),
    # Activities — the 21-state field-work lifecycle.
    *api("activities", "apps.activities.urls"),
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
