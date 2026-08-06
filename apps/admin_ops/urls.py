"""Admin platform-operations routes.

``/support`` is deliberately outside the ``/admin-ops`` prefix because every
role must be able to report a problem.
"""

from django.urls import path

from apps.admin_ops import views

urlpatterns = [
    # Admin workspaces
    path("admin-ops/team-plans", views.team_plans_view, name="admin_team_plans"),
    path("admin-ops/planning", views.admin_planning_view, name="admin_planning"),
    path("admin-ops/my-plan", views.admin_my_plan_view, name="admin_my_plan"),
    path("admin-ops/support", views.support_queue_view, name="admin_support_queue"),
    path("admin-ops/incidents", views.incidents_view, name="admin_incidents"),
    path(
        "admin-ops/incidents/<str:incident_id>",
        views.incident_detail_view,
        name="admin_incident_detail",
    ),
    path("admin-ops/maintenance", views.maintenance_view, name="admin_maintenance"),
    # Actions
    path(
        "admin-ops/work-items/<str:item_id>/schedule",
        views.schedule_work_item_view,
        name="admin_schedule_work_item",
    ),
    path(
        "admin-ops/work-items/<str:item_id>/start",
        views.start_work_item_view,
        name="admin_start_work_item",
    ),
    path(
        "admin-ops/work-items/<str:item_id>/complete",
        views.complete_work_item_view,
        name="admin_complete_work_item",
    ),
    path(
        "admin-ops/tickets/<str:ticket_id>/triage",
        views.triage_ticket_view,
        name="admin_triage_ticket",
    ),
    path(
        "admin-ops/tickets/<str:ticket_id>/resolve",
        views.resolve_ticket_view,
        name="admin_resolve_ticket",
    ),
    path(
        "admin-ops/incidents/<str:incident_id>/acknowledge",
        views.acknowledge_incident_view,
        name="admin_acknowledge_incident",
    ),
    path(
        "admin-ops/incidents/<str:incident_id>/resolve",
        views.resolve_incident_view,
        name="admin_resolve_incident",
    ),
    # Data Repair Center — controlled repair path with a dry run, reason and
    # audit row. Normal business changes use their owning workflow instead.
    path("data-repair", views.data_repair_view, name="data_repair"),
    path(
        "data-repair/<str:key>/apply",
        views.apply_repair_view,
        name="apply_data_repair",
    ),
    # Platform-wide support intake
    path("support", views.report_problem_view, name="report_problem"),
    path(
        "support/client-defect", views.client_defect_view, name="client_defect_beacon"
    ),
]
