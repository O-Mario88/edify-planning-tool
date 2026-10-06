"""Analytics endpoints — /api/analytics/* (role-scoped summaries)."""

from __future__ import annotations

import hashlib
import json
import logging

from django.core.cache import cache
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

logger = logging.getLogger(__name__)

ANALYTICS = [Permission.ANALYTICS_VIEW.value]
RECRUITMENT = [Permission.RECRUITMENT_INTELLIGENCE_VIEW.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


def _get_cache_key(prefix: str, user, params: dict) -> str:
    # sha256, not md5: this only needs to distinguish parameter sets, but an
    # md5 call without usedforsecurity=False raises on a FIPS-enforcing host,
    # which would take every analytics endpoint down rather than degrade it.
    from apps.core.scoping import resolve_user_scope, scope_cache_fingerprint

    param_str = json.dumps(params, sort_keys=True)
    param_hash = hashlib.sha256(param_str.encode("utf-8")).hexdigest()[:32]
    # Cache backends such as Memcached reject whitespace and control
    # characters in keys. Role labels are human-readable (for example
    # ``Program Lead``), so keep the isolation property without embedding the
    # label itself.
    role_hash = hashlib.sha256(str(user.active_role).encode("utf-8")).hexdigest()[:12]
    # The portfolio fingerprint, not just the user and role. Reassign a school
    # or change a reporting line and the key changes, so the previous answer
    # is never served again — see `scope_cache_fingerprint`.
    portfolio = scope_cache_fingerprint(resolve_user_scope(user))
    from apps.hr.accountability_cache import revision

    return f"analytics:allocations-v2:{revision()}:{prefix}:{user.id}:{role_hash}:{portfolio}:{param_hash}"


def _cached(prefix: str, user, params: dict, build):
    """One analytics answer, reused for five minutes.

    The cache is an optimisation over the database: when it cannot be read
    the answer is built, and when it cannot be written the answer is still
    returned. Either used to be a 500 (see apps.hr.accountability_cache).
    """
    key = _get_cache_key(prefix, user, params)
    try:
        data = cache.get(key)
    except Exception:  # noqa: BLE001 - cache loss must degrade to computation
        logger.warning("Analytics cache unreadable for %s", prefix, exc_info=True)
        return build()
    if data is None:
        data = build()
        try:
            cache.set(key, data, timeout=300)
        except Exception:  # noqa: BLE001 - the computed answer is still valid
            logger.warning("Analytics cache not written for %s", prefix, exc_info=True)
    return data


class AnalyticsDashboardView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        params = _q(request)
        return Response(
            _cached(
                "dashboard",
                request.user,
                params,
                lambda: services.dashboard_summary(request.user, params),
            )
        )


class AnalyticsLeadershipSummaryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        params = _q(request)
        return Response(
            _cached(
                "leadership_summary",
                request.user,
                params,
                lambda: services.leadership_summary(request.user, params),
            )
        )


class AnalyticsDistrictsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        params = _q(request)
        return Response(
            _cached(
                "districts",
                request.user,
                params,
                lambda: services.district_rollups(request.user, params),
            )
        )


class AnalyticsCoverageView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        params = _q(request)
        return Response(
            _cached(
                "coverage",
                request.user,
                params,
                lambda: services.coverage_summary(request.user, params),
            )
        )


class AnalyticsGeoMapView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(services.geo_map_districts(request.user, _q(request)))


class AnalyticsGeoMapDistrictView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request, district_id):
        return Response(services.geo_map_district_detail(request.user, district_id))


class AnalyticsSchoolDirectoryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(services.school_directory_summary(request.user, _q(request)))


class AnalyticsSsaPerformanceView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(services.ssa_performance(request.user, _q(request)))


class AnalyticsSsaPerformanceGroupedView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(services.ssa_performance_grouped(request.user, _q(request)))


class AnalyticsInterventionImprovementView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(services.intervention_improvement(request.user, _q(request)))


class AnalyticsSupportSsaCorrelationView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(services.support_ssa_correlation(request.user, _q(request)))


class AnalyticsStaffVsPartnerView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(
            services.staff_vs_partner_correlation(request.user, _q(request))
        )


class AnalyticsActivityPipelineView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(services.activity_pipeline(request.user, _q(request)))


class AnalyticsContributionSummaryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(services.contribution_summary(request.user, _q(request)))


class AnalyticsRecruitmentView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = RECRUITMENT

    def get(self, request):
        return Response(services.recruitment_recommendation(request.user, _q(request)))


# ── Decision engine: SSA improvement, interventions, recommendations ─────────
from . import decision_engine as de  # noqa: E402


class AnalyticsSsaImprovementView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(de.ssa_improvement(request.user, _q(request)))


class AnalyticsInterventionAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(de.intervention_analytics(request.user, _q(request)))


class AnalyticsDistrictSsaRollupView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(de.district_ssa_rollup(request.user, _q(request)))


class AnalyticsClusterSsaRollupView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(de.cluster_ssa_rollup(request.user, _q(request)))


class AnalyticsRecommendationsView(APIView):
    """Role-specific decision recommendations generated from real risk conditions."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        return Response(de.recommendations(request.user, _q(request)))


class AnalyticsRoleOverviewView(APIView):
    """A role-specific analytics overview — combines the most decision-relevant
    metrics for the caller's role into one response."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request):
        from .role_analytics import role_overview

        return Response(role_overview(request.user, _q(request)))


class AnalyticsActivityImpactView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS

    def get(self, request: Request) -> Response:
        return Response(services.activity_impact_report(request.user, _q(request)))
