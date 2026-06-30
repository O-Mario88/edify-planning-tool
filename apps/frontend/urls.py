from django.urls import path
from .views import (
    auth_views, dashboard_views, school_views, cluster_views,
    planning_views, budget_views, my_plan_views, analytics_views,
    staff_views, finance_views, partner_views, extended_views,
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
    path("schools/partial-intelligence/<str:school_id>", school_views.school_intelligence_partial, name="school_intelligence_partial"),
    
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
    
    # ── GROUP 2: Finance ──────────────────────────────────────────────────────
    path("fund-requests", finance_views.fund_requests_list_view, name="fund_requests_list"),
    path("disbursements", finance_views.disbursements_view, name="disbursements"),
    path("budgets/overview", finance_views.budget_overview_view, name="budget_overview"),
    path("cost-settings", finance_views.cost_settings_view, name="cost_settings"),
    
    # ── GROUP 3: Partners ─────────────────────────────────────────────────────
    path("partners", partner_views.partners_list_view, name="partners_list"),
    path("partners/<str:partner_id>", partner_views.partner_detail_view, name="partner_detail"),
    path("partner/today", partner_views.partner_today_view, name="partner_today"),
    path("partner/schools", partner_views.partner_schools_view, name="partner_schools"),
    path("partner/activities", partner_views.partner_activities_view, name="partner_activities"),
    path("partner/evidence", partner_views.partner_evidence_view, name="partner_evidence"),
    
    # ── GROUP 4: SSA, FY & Planning ──────────────────────────────────────────
    path("ssa", extended_views.ssa_master_view, name="ssa_master"),
    path("fy", extended_views.fy_overview_view, name="fy_overview"),
    path("calendar", extended_views.calendar_view, name="calendar"),
    path("work-plan", extended_views.work_plan_view, name="work_plan"),
    
    # ── GROUP 5: Districts, Reports & Coverage ────────────────────────────────
    path("districts", extended_views.districts_list_view, name="districts_list"),
    path("districts/<str:district_id>", extended_views.district_detail_view, name="district_detail"),
    path("reports", extended_views.reports_view, name="reports"),
    path("coverage", extended_views.coverage_view, name="coverage"),
    
    # ── GROUP 6: Admin, Settings, Messages, Leaves & Search ───────────────────
    path("admin-panel", extended_views.admin_panel_view, name="admin_panel"),
    path("admin/users", extended_views.admin_users_view, name="admin_users"),
    path("admin/users/<str:user_id>", extended_views.admin_user_detail_view, name="admin_user_detail"),
    path("admin/audit-log", extended_views.audit_log_view, name="audit_log"),
    path("settings", extended_views.settings_view, name="settings"),
    path("search", extended_views.search_view, name="search"),
    path("messages", extended_views.messages_list_view, name="messages_list"),
    path("messages/<str:message_id>", extended_views.message_detail_view, name="message_detail"),
    path("leave-requests", extended_views.leave_requests_view, name="leave_requests"),
    path("map", extended_views.map_view, name="map"),
    
    # ── GROUP 7: Core Schools, Projects, Debriefs, Completed, Quality, Help ───
    path("core-schools", extended_views.core_schools_view, name="core_schools"),
    path("core-schools/<str:plan_id>", extended_views.core_school_detail_view, name="core_school_detail"),
    path("projects", extended_views.projects_list_view, name="projects_list"),
    path("projects/<str:project_id>", extended_views.project_detail_view, name="project_detail"),
    path("debriefs", extended_views.debriefs_list_view, name="debriefs_list"),
    path("debriefs/<str:debrief_id>", extended_views.debrief_detail_view, name="debrief_detail"),
    path("completed-activities", extended_views.completed_activities_view, name="completed_activities"),
    path("quality-checks", extended_views.quality_checks_view, name="quality_checks"),
    path("help", extended_views.help_view, name="help"),
    
    # Root redirects to dashboard (which handles auth redirect)
    path("", dashboard_views.dashboard_view, name="index"),
]
