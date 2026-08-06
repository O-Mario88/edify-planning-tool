from django.urls import path

from . import views

urlpatterns = [
    path("dashboard", views.AnalyticsDashboardView.as_view(), name="dashboard"),
    path(
        "leadership-summary",
        views.AnalyticsLeadershipSummaryView.as_view(),
        name="leadership-summary",
    ),
    path("districts", views.AnalyticsDistrictsView.as_view(), name="districts"),
    path("coverage", views.AnalyticsCoverageView.as_view(), name="coverage"),
    path("geo-map", views.AnalyticsGeoMapView.as_view(), name="geo-map"),
    path(
        "geo-map/district/<str:district_id>",
        views.AnalyticsGeoMapDistrictView.as_view(),
        name="geo-map-district",
    ),
    path(
        "school-directory",
        views.AnalyticsSchoolDirectoryView.as_view(),
        name="school-directory",
    ),
    path(
        "ssa-performance",
        views.AnalyticsSsaPerformanceView.as_view(),
        name="ssa-performance",
    ),
    path(
        "ssa-performance-grouped",
        views.AnalyticsSsaPerformanceGroupedView.as_view(),
        name="ssa-performance-grouped",
    ),
    path(
        "intervention-improvement",
        views.AnalyticsInterventionImprovementView.as_view(),
        name="intervention-improvement",
    ),
    path(
        "support-ssa-correlation",
        views.AnalyticsSupportSsaCorrelationView.as_view(),
        name="support-ssa-correlation",
    ),
    path(
        "staff-vs-partner-correlation",
        views.AnalyticsStaffVsPartnerView.as_view(),
        name="staff-vs-partner",
    ),
    path(
        "activity-pipeline",
        views.AnalyticsActivityPipelineView.as_view(),
        name="activity-pipeline",
    ),
    path(
        "activity-impact",
        views.AnalyticsActivityImpactView.as_view(),
        name="activity-impact",
    ),
    path(
        "contribution-summary",
        views.AnalyticsContributionSummaryView.as_view(),
        name="contribution-summary",
    ),
    path(
        "recruitment-recommendation",
        views.AnalyticsRecruitmentView.as_view(),
        name="recruitment",
    ),
    # Decision engine — SSA improvement, interventions, recommendations.
    path(
        "ssa/improvement",
        views.AnalyticsSsaImprovementView.as_view(),
        name="ssa-improvement",
    ),
    path(
        "ssa/interventions",
        views.AnalyticsInterventionAnalyticsView.as_view(),
        name="ssa-interventions",
    ),
    path(
        "ssa/district-rollup",
        views.AnalyticsDistrictSsaRollupView.as_view(),
        name="ssa-district-rollup",
    ),
    path(
        "ssa/cluster-rollup",
        views.AnalyticsClusterSsaRollupView.as_view(),
        name="ssa-cluster-rollup",
    ),
    path(
        "recommendations",
        views.AnalyticsRecommendationsView.as_view(),
        name="recommendations",
    ),
    path(
        "role-overview", views.AnalyticsRoleOverviewView.as_view(), name="role-overview"
    ),
]
