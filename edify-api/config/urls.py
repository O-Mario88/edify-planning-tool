"""Root URL configuration.

A global `/api` prefix mirrors the NestJS backend (setGlobalPrefix('api')) so the
frontend's existing EDIFY_API_URL contract keeps working unchanged. The health
probe lives at the prefix root; everything else hangs off `api/`.
"""
from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

# API namespace wiring is added incrementally as each module lands.
urlpatterns = [
    path("admin/", admin.site.urls),
    # Health probe — public, DB ping. Matches NestJS GET /api/health.
    path("api/health/", lambda r: _health(r), name="health"),
    # Auth — public login/refresh/reset + JWT-gated /me.
    path("api/auth/", include("apps.accounts.urls")),
]


def _health(request):
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
