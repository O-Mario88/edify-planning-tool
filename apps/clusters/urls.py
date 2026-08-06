"""Clusters URL routes — /api/clusters/*.

Static segments (sub-counties-without-clusters, planning, from-school, assign,
recommendations/:id, eligible-for-school/:id) declared before :id param.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.ClusterListCreateView.as_view(), name="list"),
    path(
        "sub-counties-without-clusters",
        views.ClusterSubCountiesWithoutView.as_view(),
        name="sub-counties-without",
    ),
    path("planning", views.ClusterPlanningView.as_view(), name="planning"),
    path("from-school", views.ClusterFromSchoolView.as_view(), name="from-school"),
    path("assign", views.ClusterAssignView.as_view(), name="assign"),
    path(
        "recommendations/<str:school_id>",
        views.ClusterRecommendationsView.as_view(),
        name="recommendations",
    ),
    path(
        "eligible-for-school/<str:school_id>",
        views.ClusterEligibleForSchoolView.as_view(),
        name="eligible",
    ),
    path("<str:cluster_id>", views.ClusterDetailView.as_view(), name="detail"),
    path(
        "<str:cluster_id>/intelligence",
        views.ClusterIntelligenceView.as_view(),
        name="intelligence",
    ),
    path(
        "<str:cluster_id>/schools", views.ClusterSchoolsView.as_view(), name="schools"
    ),
    path(
        "<str:cluster_id>/intervention-summary",
        views.ClusterInterventionSummaryView.as_view(),
        name="intervention-summary",
    ),
    path(
        "<str:cluster_id>/weakest-interventions",
        views.ClusterWeakestInterventionsView.as_view(),
        name="weakest-interventions",
    ),
    path(
        "<str:cluster_id>/activity-impact",
        views.ClusterActivityImpactView.as_view(),
        name="activity-impact",
    ),
    path("<str:cluster_id>/impact", views.ClusterImpactView.as_view(), name="impact"),
]
