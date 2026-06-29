from django.urls import path
from .views import (
    auth_views, dashboard_views, school_views, cluster_views,
    planning_views, budget_views, my_plan_views, analytics_views,
    staff_views,
)

app_name = "frontend"

urlpatterns = [
    # Auth
    path("login", auth_views.login_view, name="login"),
    path("logout", auth_views.logout_view, name="logout"),
    path("auth/switch-role", auth_views.switch_role_view, name="switch_role"),
    
    # Dashboards
    path("dashboard", dashboard_views.dashboard_view, name="dashboard"),
    
    # Schools
    path("schools", school_views.school_directory_view, name="schools_directory"),
    path("schools/upload", school_views.school_upload_view, name="schools_upload"),
    path("schools/<str:school_id>", school_views.school_detail_view, name="school_detail"),
    
    # Clusters
    path("clusters", cluster_views.cluster_list_view, name="cluster_list"),
    path("clusters/<str:cluster_id>", cluster_views.cluster_detail_view, name="cluster_detail"),
    path("partials/clusters/<str:cluster_id>/schools", cluster_views.cluster_schools_partial, name="cluster_schools_partial"),
    
    # Planning
    path("planning", planning_views.planning_dashboard_view, name="planning_dashboard"),
    path("planning/schedule", planning_views.schedule_activity_form_view, name="planning_schedule"),
    path("partials/costing/preview", planning_views.cost_preview_partial, name="cost_preview"),
    
    # Budgets & Fund Requests
    path("budgets/monthly", budget_views.monthly_budget_view, name="monthly_budget"),
    path("fund-requests/weekly", budget_views.weekly_fund_requests_view, name="weekly_fund_requests"),
    path("fund-requests/weekly/<str:request_id>", budget_views.weekly_fund_request_detail_view, name="weekly_fund_request_detail"),
    path("fund-requests/weekly/<str:request_id>/confirm", budget_views.weekly_fund_request_confirm_action, name="weekly_fund_request_confirm"),
    path("fund-requests/weekly/<str:request_id>/disburse", budget_views.weekly_fund_request_disburse_action, name="weekly_fund_request_disburse"),
    
    # My Plan
    path("my-plan", my_plan_views.my_plan_view, name="my_plan"),
    path("my-plan/<str:activity_id>", my_plan_views.activity_detail_view, name="activity_detail"),
    path("my-plan/<str:activity_id>/reschedule", my_plan_views.reschedule_activity_action, name="reschedule_activity"),
    path("my-plan/<str:activity_id>/complete", my_plan_views.complete_activity_action, name="complete_activity"),
    
    # PL Review Queue
    path("pl/review-queue", my_plan_views.pl_queue_view, name="pl_review_queue"),
    path("pl/review-queue/<str:activity_id>/confirm", my_plan_views.pl_confirm_action, name="pl_confirm"),
    path("pl/review-queue/<str:activity_id>/return", my_plan_views.pl_return_action, name="pl_return"),
    
    # IA Verification Queue
    path("ia/verification-queue", my_plan_views.ia_queue_view, name="ia_verification_queue"),
    path("ia/verification-queue/<str:activity_id>/confirm", my_plan_views.ia_confirm_action, name="ia_confirm"),
    
    # Analytics & System Health
    path("analytics", analytics_views.analytics_dashboard_view, name="analytics_dashboard"),
    path("system-health", analytics_views.system_health_view, name="system_health"),
    
    # ── GROUP 1: Core Operations ──────────────────────────────────────────────
    
    # Staff Directory & Profiles
    path("staff", staff_views.staff_directory_view, name="staff_directory"),
    path("staff/<str:user_id>", staff_views.staff_profile_view, name="staff_profile"),
    
    # Today
    path("today", staff_views.today_view, name="today"),
    
    # Visits
    path("visits", staff_views.visits_log_view, name="visits_log"),
    
    # Trainings
    path("trainings", staff_views.trainings_log_view, name="trainings_log"),
    
    # Evidence
    path("evidence", staff_views.evidence_gallery_view, name="evidence_gallery"),
    
    # Targets (My Targets)
    path("my-targets", staff_views.my_targets_view, name="my_targets"),
    
    # My Team (PL view)
    path("my-team", staff_views.my_team_view, name="my_team"),
    
    # Notifications
    path("notifications", staff_views.notifications_view, name="notifications"),
    path("notifications/<str:notif_id>/read", staff_views.mark_notification_read, name="mark_notif_read"),
    
    # Profile
    path("profile", staff_views.profile_view, name="profile"),
    
    # Root redirects to dashboard (which handles auth redirect)
    path("", dashboard_views.dashboard_view, name="index"),
]
