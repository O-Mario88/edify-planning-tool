"""Analytics endpoints — /api/analytics/* (role-scoped summaries)."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

ANALYTICS = [Permission.ANALYTICS_VIEW.value]
RECRUITMENT = [Permission.RECRUITMENT_INTELLIGENCE_VIEW.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class AnalyticsDashboardView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.dashboard_summary(request.user, _q(request)))


class AnalyticsLeadershipSummaryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.leadership_summary(request.user, _q(request)))


class AnalyticsDistrictsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.district_rollups(request.user, _q(request)))


class AnalyticsCoverageView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.coverage_summary(request.user, _q(request)))


class AnalyticsGeoMapView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.geo_map_districts(request.user, _q(request)))


class AnalyticsGeoMapDistrictView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request, district_id): return Response(services.geo_map_district_detail(request.user, district_id))


class AnalyticsSchoolDirectoryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.school_directory_summary(request.user, _q(request)))


class AnalyticsSsaPerformanceView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.ssa_performance(request.user, _q(request)))


class AnalyticsSsaPerformanceGroupedView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.ssa_performance_grouped(request.user, _q(request)))


class AnalyticsInterventionImprovementView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.intervention_improvement(request.user, _q(request)))


class AnalyticsSupportSsaCorrelationView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.support_ssa_correlation(request.user, _q(request)))


class AnalyticsStaffVsPartnerView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.staff_vs_partner_correlation(request.user, _q(request)))


class AnalyticsActivityPipelineView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.activity_pipeline(request.user, _q(request)))


class AnalyticsContributionSummaryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(services.contribution_summary(request.user, _q(request)))


class AnalyticsRecruitmentView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = RECRUITMENT
    def get(self, request): return Response(services.recruitment_recommendation(request.user, _q(request)))


# ── Decision engine: SSA improvement, interventions, recommendations ─────────
from . import decision_engine as de  # noqa: E402


class AnalyticsSsaImprovementView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(de.ssa_improvement(request.user, _q(request)))


class AnalyticsInterventionAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(de.intervention_analytics(request.user, _q(request)))


class AnalyticsDistrictSsaRollupView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(de.district_ssa_rollup(request.user, _q(request)))


class AnalyticsClusterSsaRollupView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(de.cluster_ssa_rollup(request.user, _q(request)))


class AnalyticsRecommendationsView(APIView):
    """Role-specific decision recommendations generated from real risk conditions."""
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request): return Response(de.recommendations(request.user, _q(request)))


class AnalyticsRoleOverviewView(APIView):
    """A role-specific analytics overview — combines the most decision-relevant
    metrics for the caller's role into one response."""
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ANALYTICS
    def get(self, request):
        from .role_analytics import role_overview
        return Response(role_overview(request.user, _q(request)))
