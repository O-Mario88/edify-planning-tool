from django.urls import path

from . import views

urlpatterns = [
    path("setup", views.PlanningSetupView.as_view(), name="setup"),
    path("core", views.PlanningCoreView.as_view(), name="core"),
    path("plan-builder", views.PlanningPlanBuilderView.as_view(), name="plan-builder"),
    path("recompute/<str:school_id>", views.PlanningRecomputeView.as_view(), name="recompute"),
    path("schedule-school-visit", views.ScheduleSchoolVisitView.as_view(), name="schedule-visit"),
    path("assign-school-visit-to-partner", views.AssignSchoolVisitToPartnerView.as_view(), name="assign-visit-partner"),
    path("schedule-cluster-training", views.ScheduleClusterTrainingView.as_view(), name="schedule-training"),
    path("schedule-cluster-activity", views.ScheduleClusterActivityView.as_view(), name="schedule-cluster-activity"),
    # plans list (GET) + create (POST) share the path.
    path("plans", views.PlanListCreateView.as_view(), name="plans-list-create"),
    path("plans/<str:plan_id>", views.PlanDetailView.as_view(), name="plan-detail"),
    path("plans/<str:plan_id>/activities", views.PlanAddActivityView.as_view(), name="plan-add-activity"),
    path("plans/<str:plan_id>/submit", views.PlanSubmitView.as_view(), name="plan-submit"),
    path("plans/<str:plan_id>/approve", views.PlanApproveView.as_view(), name="plan-approve"),
    path("plans/<str:plan_id>/return", views.PlanReturnView.as_view(), name="plan-return"),
]
