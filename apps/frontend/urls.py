from django.urls import path
from .views import (
    rvp_views,
    auth_views,
    dashboard_views,
    school_views,
    cluster_views,
    planning_views,
    budget_views,
    my_plan_views,
    analytics_views,
    staff_views,
    finance_views,
    partner_views,
    extended_views,
    message_views,
    core_schools_views,
    ssa_views,
    ia_views,
    finance_operating_views,
    closure_views,
    leave_views,
    hr_views,
    pd_views,
    debrief_views,
)

app_name = "frontend"

urlpatterns = [
    # Auth
    path("login", auth_views.login_view, name="login"),
    path("logout", auth_views.logout_view, name="logout"),
    path("auth/switch-role", auth_views.switch_role_view, name="switch_role"),
    path(
        "change-password", auth_views.force_change_password_view, name="change_password"
    ),
    # Dashboards
    path("dashboard", dashboard_views.dashboard_view, name="dashboard"),
    path(
        "dashboard/pl-drilldown",
        dashboard_views.pl_dashboard_drilldown_view,
        name="pl_dashboard_drilldown",
    ),
    path(
        "dashboard/pl-approve",
        dashboard_views.pl_dashboard_approve_view,
        name="pl_dashboard_approve",
    ),
    path(
        "dashboard/cd-approve",
        dashboard_views.cd_dashboard_approve_view,
        name="cd_dashboard_approve",
    ),
    # To-Do operating queue (system-generated, role-scoped)
    path("todos", extended_views.todos_view, name="todos"),
    # PL Fund Approval (team-scoped finance gate)
    path(
        "fund-approvals", extended_views.pl_fund_approvals_view, name="fund_approvals"
    ),
    path(
        "fund-approvals/detail",
        extended_views.pl_fund_detail_view,
        name="fund_approvals_detail",
    ),
    path(
        "fund-approvals/return",
        extended_views.pl_fund_return_modal_view,
        name="fund_approvals_return",
    ),
    path(
        "fund-approvals/action",
        extended_views.pl_fund_action_view,
        name="fund_approvals_action",
    ),
    # Schools
    path("schools", school_views.school_directory_view, name="schools_directory"),
    path("schools/upload", school_views.school_upload_view, name="schools_upload"),
    path(
        "schools/upload/template",
        school_views.school_template_download_view,
        name="school_template_download",
    ),
    path(
        "schools/upload/<str:batch_id>/preview",
        school_views.school_upload_preview_view,
        name="school_upload_preview",
    ),
    path(
        "schools/uploads/<str:batch_id>/result",
        school_views.school_import_result_view,
        name="school_import_result",
    ),
    path(
        "schools/bulk-assign-cluster",
        school_views.bulk_assign_cluster_view,
        name="bulk_assign_cluster",
    ),
    path(
        "schools/bulk-assign-project",
        school_views.bulk_assign_project_view,
        name="bulk_assign_project",
    ),
    path(
        "schools/bulk-match-staff",
        school_views.bulk_match_staff_view,
        name="bulk_match_staff",
    ),
    path("schools/add-school", school_views.add_school_view, name="add_school"),
    path(
        "schools/partial-intelligence/<str:school_id>",
        school_views.school_intelligence_partial,
        name="school_intelligence_partial",
    ),
    path(
        "schools/<str:school_id>", school_views.school_detail_view, name="school_detail"
    ),
    path(
        "schools/<str:school_id>/change-type",
        school_views.school_change_type_view,
        name="school_change_type",
    ),
    path(
        "schools/<str:school_id>/add-to-cluster",
        school_views.add_to_cluster_drawer_view,
        name="add_to_cluster_drawer",
    ),
    path(
        "schools/<str:school_id>/edit-drawer",
        school_views.school_edit_drawer_view,
        name="school_edit_drawer",
    ),
    path(
        "schools/create-drawer",
        school_views.school_onboard_drawer_view,
        name="school_onboard_drawer",
    ),
    path(
        "schools/<str:school_id>/assign-to-project",
        school_views.assign_to_project_drawer_view,
        name="assign_to_project_drawer",
    ),
    # Clusters
    path("clusters", cluster_views.cluster_list_view, name="cluster_list"),
    path(
        "clusters/cost-preview",
        cluster_views.cluster_cost_preview_partial,
        name="cluster_cost_preview",
    ),
    path(
        "clusters/schedule-activity",
        cluster_views.cluster_schedule_activity_view,
        name="cluster_schedule_activity",
    ),
    path("clusters/create", cluster_views.create_cluster_view, name="create_cluster"),
    path(
        "clusters/create-drawer",
        cluster_views.create_cluster_drawer_view,
        name="create_cluster_drawer",
    ),
    path(
        "clusters/eligible-staff",
        cluster_views.eligible_staff_options_view,
        name="eligible_staff_options",
    ),
    path(
        "clusters/<str:cluster_id>/edit-drawer",
        cluster_views.edit_cluster_drawer_view,
        name="edit_cluster_drawer",
    ),
    path(
        "clusters/<str:cluster_id>/edit",
        cluster_views.edit_cluster_view,
        name="edit_cluster",
    ),
    path(
        "clusters/planner-drawer",
        cluster_views.planner_drawer_view,
        name="cluster_planner_drawer",
    ),
    path(
        "clusters/schedule-training-drawer",
        cluster_views.schedule_training_drawer_view,
        name="schedule_training_drawer",
    ),
    path(
        "clusters/schedule-meeting-drawer",
        cluster_views.schedule_meeting_drawer_view,
        name="schedule_meeting_drawer",
    ),
    path(
        "clusters/detail-drawer/<str:cluster_id>",
        cluster_views.cluster_detail_drawer_view,
        name="cluster_detail_drawer",
    ),
    path(
        "clusters/impact-drawer/<str:cluster_id>",
        cluster_views.intervention_impact_drawer_view,
        name="cluster_impact_drawer",
    ),
    path(
        "clusters/impact/<str:cluster_id>",
        cluster_views.cluster_impact_partial,
        name="cluster_impact_partial",
    ),
    path(
        "clusters/<str:cluster_id>",
        cluster_views.cluster_detail_view,
        name="cluster_detail",
    ),
    path(
        "partials/clusters/<str:cluster_id>/schools",
        cluster_views.cluster_schools_partial,
        name="cluster_schools_partial",
    ),
    path(
        "clusters/<str:cluster_id>/bulk-assign-drawer",
        cluster_views.cluster_bulk_assign_drawer_view,
        name="cluster_bulk_assign_drawer",
    ),
    # Planning
    path("planning", planning_views.planning_dashboard_view, name="planning_dashboard"),
    path(
        "planning/schedule",
        planning_views.schedule_activity_form_view,
        name="planning_schedule",
    ),
    path(
        "planning/schedule-modal",
        planning_views.schedule_modal_view,
        name="planning_schedule_modal",
    ),
    path(
        "planning/schedule-action",
        planning_views.schedule_action_view,
        name="planning_schedule_action",
    ),
    path(
        "planning/assign-partner-modal",
        planning_views.assign_partner_modal_view,
        name="planning_assign_partner_modal",
    ),
    path(
        "planning/assign-partner-action",
        planning_views.assign_partner_action_view,
        name="planning_assign_partner_action",
    ),
    path(
        "planning/intelligence",
        planning_views.planning_intelligence_view,
        name="planning_intelligence",
    ),
    path(
        "planning/bulk-action",
        planning_views.bulk_action_view,
        name="planning_bulk_action",
    ),
    path(
        "planning/route-preview",
        planning_views.route_preview_view,
        name="planning_route_preview",
    ),
    path(
        "partials/costing/preview",
        planning_views.cost_preview_partial,
        name="cost_preview",
    ),
    # Budgets & Fund Requests
    path("budgets/monthly", budget_views.monthly_budget_view, name="monthly_budget"),
    path(
        "fund-requests/weekly",
        budget_views.weekly_fund_requests_view,
        name="weekly_fund_requests",
    ),
    path(
        "fund-requests/weekly/<str:request_id>",
        budget_views.weekly_fund_request_detail_view,
        name="weekly_fund_request_detail",
    ),
    path(
        "fund-requests/weekly/<str:request_id>/confirm",
        budget_views.weekly_fund_request_confirm_action,
        name="weekly_fund_request_confirm",
    ),
    path(
        "fund-requests/weekly/<str:request_id>/self-funded",
        budget_views.weekly_fund_request_self_funded_action,
        name="weekly_fund_request_self_funded",
    ),
    path(
        "fund-requests/weekly/<str:request_id>/approve",
        budget_views.weekly_fund_request_approve_action,
        name="weekly_fund_request_approve",
    ),
    path(
        "fund-requests/weekly/<str:request_id>/return",
        budget_views.weekly_fund_request_return_action,
        name="weekly_fund_request_return",
    ),
    path(
        "fund-requests/weekly/<str:request_id>/disburse",
        budget_views.weekly_fund_request_disburse_action,
        name="weekly_fund_request_disburse",
    ),
    path(
        "fund-requests/generate-request",
        budget_views.generate_request_action,
        name="generate_request_action",
    ),
    # My Plan & Activities Drawers/Pages
    path("my-plan", my_plan_views.my_plan_view, name="my_plan"),
    path(
        "my-plan/<str:activity_id>",
        my_plan_views.activity_detail_view,
        name="activity_detail",
    ),
    path(
        "my-plan/<str:activity_id>/complete-drawer",
        my_plan_views.complete_drawer_view,
        name="complete_drawer",
    ),
    path(
        "my-plan/<str:activity_id>/reschedule-drawer",
        my_plan_views.reschedule_drawer_view,
        name="reschedule_drawer",
    ),
    path(
        "my-plan/<str:activity_id>/reschedule",
        my_plan_views.reschedule_activity_action,
        name="reschedule_activity",
    ),
    path(
        "my-plan/<str:activity_id>/complete",
        my_plan_views.complete_activity_action,
        name="complete_activity",
    ),
    path(
        "my-plan/<str:activity_id>/accountability",
        my_plan_views.accountability_action,
        name="accountability_action",
    ),
    path(
        "activities/<str:activity_id>",
        my_plan_views.activity_detail_view,
        name="activity_detail_full",
    ),
    path(
        "activities/<str:activity_id>/start",
        my_plan_views.start_activity_drawer_view,
        name="start_activity_drawer",
    ),
    path(
        "activities/<str:activity_id>/start/action",
        my_plan_views.start_activity_action,
        name="start_activity_action",
    ),
    path(
        "activities/<str:activity_id>/complete",
        my_plan_views.complete_activity_drawer_view,
        name="complete_activity_drawer",
    ),
    path(
        "activities/<str:activity_id>/complete/action",
        my_plan_views.complete_activity_action,
        name="complete_activity_action",
    ),
    path(
        "activities/<str:activity_id>/evidence",
        my_plan_views.evidence_upload_drawer_view,
        name="evidence_upload_drawer",
    ),
    path(
        "activities/<str:activity_id>/evidence/action",
        my_plan_views.evidence_upload_action,
        name="evidence_upload_action",
    ),
    path(
        "activities/<str:activity_id>/evidence/detail",
        my_plan_views.evidence_packet_view,
        name="evidence_packet",
    ),
    path(
        "activities/<str:activity_id>/salesforce-id",
        my_plan_views.salesforce_id_drawer_view,
        name="salesforce_id_drawer",
    ),
    path(
        "activities/<str:activity_id>/salesforce-id/action",
        my_plan_views.salesforce_id_action,
        name="salesforce_id_action",
    ),
    path(
        "activities/<str:activity_id>/submit",
        my_plan_views.submit_for_review_drawer_view,
        name="submit_for_review_drawer",
    ),
    path(
        "activities/<str:activity_id>/submit/action",
        my_plan_views.submit_for_review_action,
        name="submit_for_review_action",
    ),
    path(
        "activities/<str:activity_id>/timeline",
        my_plan_views.activity_timeline_drawer_view,
        name="activity_timeline_drawer",
    ),
    path(
        "activities/<str:activity_id>/attendance",
        my_plan_views.attendance_upload_drawer_view,
        name="attendance_upload_drawer",
    ),
    path(
        "activities/<str:activity_id>/attendance/action",
        my_plan_views.attendance_upload_action,
        name="attendance_upload_action",
    ),
    path(
        "activities/<str:activity_id>/ssa-upload",
        my_plan_views.ssa_evidence_upload_drawer_view,
        name="ssa_evidence_upload_drawer",
    ),
    path(
        "activities/<str:activity_id>/ssa-upload/action",
        my_plan_views.ssa_evidence_upload_action,
        name="ssa_evidence_upload_action",
    ),
    path("evidence/", my_plan_views.evidence_center_view, name="evidence_center"),
    path(
        "evidence/returned",
        my_plan_views.returned_evidence_view,
        name="returned_evidence",
    ),
    path(
        "accounts/activity-evidence/<str:activity_id>",
        my_plan_views.accounts_activity_evidence_view,
        name="accounts_activity_evidence",
    ),
    # PL Review Queue
    path("pl/review-queue", my_plan_views.pl_queue_view, name="pl_review_queue"),
    path(
        "pl/review-queue/<str:activity_id>/confirm",
        my_plan_views.pl_confirm_action,
        name="pl_confirm",
    ),
    path(
        "pl/review-queue/<str:activity_id>/return",
        my_plan_views.pl_return_action,
        name="pl_return",
    ),
    # IA Quality Certification Layer
    path(
        "ia/verification/",
        ia_views.ia_verification_queue_view,
        name="ia_verification_queue",
    ),
    path(
        "ia/verification/<str:activity_id>/",
        ia_views.ia_review_workspace_view,
        name="ia_review_workspace",
    ),
    path(
        "ia/verification/<str:activity_id>/verify",
        ia_views.ia_verify_action,
        name="ia_verify_action",
    ),
    path(
        "ia/verification/<str:activity_id>/return",
        ia_views.ia_return_action,
        name="ia_return_action",
    ),
    path("ia/returned/", ia_views.ia_returned_view, name="ia_returned"),
    path("ia/history/", ia_views.ia_history_view, name="ia_history"),
    path("ia/duplicates/", ia_views.ia_duplicates_view, name="ia_duplicates"),
    path(
        "ia/duplicates/<str:duplicate_id>/action",
        ia_views.ia_duplicate_action,
        name="ia_duplicate_action",
    ),
    path("ia/dashboard/", ia_views.ia_dashboard_view, name="ia_dashboard"),
    path("ia/notifications/", ia_views.ia_notifications_view, name="ia_notifications"),
    path("ia/compare/", ia_views.ia_compare_view, name="ia_compare"),
    path(
        "activities/<str:activity_id>/timeline/",
        ia_views.activity_timeline_view,
        name="activity_timeline",
    ),
    # Analytics & System Health
    path(
        "analytics",
        analytics_views.analytics_dashboard_view,
        name="analytics_dashboard",
    ),
    path("analytics/", analytics_views.analytics_dashboard_view),
    # Program Lead Analytics cockpit (supervised-team scope).
    path(
        "analytics/program-lead",
        analytics_views.pl_analytics_view,
        name="pl_analytics",
    ),
    path(
        "analytics/program-lead/drilldown",
        analytics_views.pl_analytics_drilldown_view,
        name="pl_analytics_drilldown",
    ),
    path(
        "analytics/program-lead/export",
        analytics_views.pl_analytics_export_view,
        name="pl_analytics_export",
    ),
    path(
        "analytics/country-director",
        analytics_views.cd_analytics_view,
        name="cd_analytics",
    ),
    path(
        "analytics/country-director/drilldown",
        analytics_views.cd_analytics_drilldown_view,
        name="cd_analytics_drilldown",
    ),
    path(
        "analytics/country-director/export",
        analytics_views.cd_analytics_export_view,
        name="cd_analytics_export",
    ),
    path(
        "analytics/drilldown",
        analytics_views.analytics_drilldown_view,
        name="analytics_drilldown",
    ),
    path(
        "analytics/schedule-report",
        analytics_views.analytics_schedule_report_view,
        name="analytics_schedule_report",
    ),
    path(
        "analytics/customize-dashboard",
        analytics_views.analytics_customize_dashboard_view,
        name="analytics_customize_dashboard",
    ),
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
    path(
        "my-targets/area-drawer",
        staff_views.my_targets_area_drawer_view,
        name="my_targets_area_drawer",
    ),
    path(
        "my-targets/export",
        staff_views.my_targets_export_view,
        name="my_targets_export",
    ),
    path("my-targets/mscs", staff_views.mscs_submit_view, name="my_targets_mscs"),
    # Professional Development (My Professional Development) — one shared
    # employee-owned workflow, same route for every eligible role.
    path(
        "my-professional-development",
        pd_views.my_professional_development_view,
        name="my_professional_development",
    ),
    path("my-professional-development/", pd_views.my_professional_development_view),
    path(
        "my-professional-development/request",
        pd_views.pd_request_view,
        name="pd_request",
    ),
    path(
        "my-professional-development/request/<str:request_id>/evidence",
        pd_views.pd_evidence_upload_view,
        name="pd_evidence_upload",
    ),
    path(
        "my-professional-development/request/<str:request_id>/certificate",
        pd_views.pd_certificate_upload_view,
        name="pd_certificate_upload",
    ),
    path(
        "my-professional-development/request/<str:request_id>/action",
        pd_views.pd_action_view,
        name="pd_action",
    ),
    path(
        "my-professional-development/fund/<str:fund_request_id>/action",
        pd_views.pd_fund_action_view,
        name="pd_fund_action",
    ),
    path(
        "my-professional-development/export", pd_views.pd_export_view, name="pd_export"
    ),
    path(
        "my-professional-development/allocation-history",
        pd_views.pd_allocation_history_view,
        name="pd_allocation_history",
    ),
    path(
        "my-professional-development/certificate/<str:file_id>",
        pd_views.pd_certificate_file_view,
        name="pd_certificate_file",
    ),
    path(
        "my-professional-development/evidence/<str:file_id>",
        pd_views.pd_evidence_file_view,
        name="pd_evidence_file",
    ),
    path("team-targets", staff_views.team_targets_view, name="team_targets"),
    path("team-targets/", staff_views.team_targets_view),
    path(
        "team-targets/staff-drawer",
        staff_views.team_targets_staff_drawer_view,
        name="team_targets_staff_drawer",
    ),
    path(
        "team-targets/matrix",
        staff_views.team_targets_matrix_view,
        name="team_targets_matrix",
    ),
    path(
        "team-targets/day", staff_views.team_targets_day_view, name="team_targets_day"
    ),
    path(
        "team-targets/recovery",
        staff_views.team_targets_recovery_view,
        name="team_targets_recovery",
    ),
    path(
        "team-targets/sfid-backlog",
        staff_views.team_targets_sfid_backlog_view,
        name="team_targets_sfid_backlog",
    ),
    path(
        "team-targets/catchup",
        staff_views.team_targets_catchup_create_view,
        name="team_targets_catchup_create",
    ),
    path(
        "team-targets/catchup/<str:plan_id>/action",
        staff_views.team_targets_catchup_action_view,
        name="team_targets_catchup_action",
    ),
    path(
        "team-targets/export",
        staff_views.team_targets_export_view,
        name="team_targets_export",
    ),
    # Personal Time Off & Leave Workflow
    path(
        "personal-time-off",
        leave_views.personal_time_off_view,
        name="personal_time_off",
    ),
    path("personal-time-off/", leave_views.personal_time_off_view),
    path(
        "personal-time-off/request",
        leave_views.request_leave_drawer_view,
        name="request_leave_drawer",
    ),
    path("personal-time-off/request/", leave_views.request_leave_drawer_view),
    path(
        "personal-time-off/eligible-cover",
        leave_views.eligible_cover_api,
        name="eligible_cover_api",
    ),
    path("leave/tracker", leave_views.leave_tracker_view, name="leave_tracker"),
    path("leave/tracker/", leave_views.leave_tracker_view),
    path("leave/approvals", leave_views.leave_approvals_view, name="leave_approvals"),
    path("leave/approvals/", leave_views.leave_approvals_view),
    path(
        "leave/approvals/<str:leave_id>/approve",
        leave_views.leave_approve_action,
        name="leave_approve_action",
    ),
    path(
        "leave/approvals/<str:leave_id>/reject",
        leave_views.leave_reject_action,
        name="leave_reject_action",
    ),
    path(
        "leave/approvals/<str:leave_id>/return",
        leave_views.leave_return_action,
        name="leave_return_action",
    ),
    path(
        "leave/coverage/<str:leave_id>/accept",
        leave_views.leave_coverage_accept_action,
        name="leave_coverage_accept_action",
    ),
    path(
        "leave/coverage/<str:leave_id>/decline",
        leave_views.leave_coverage_decline_action,
        name="leave_coverage_decline_action",
    ),
    path(
        "leave/approvals/<str:leave_id>/reassign",
        leave_views.leave_reassign_coverage_action,
        name="leave_reassign_coverage_action",
    ),
    path(
        "leave/approvals/<str:leave_id>/escalate",
        leave_views.leave_escalate_action,
        name="leave_escalate_action",
    ),
    path(
        "leave/approvals/<str:leave_id>/impact",
        leave_views.leave_impact_partial,
        name="leave_impact_partial",
    ),
    path("leave/approvals/<str:leave_id>/impact/", leave_views.leave_impact_partial),
    path("leave/coverage", leave_views.leave_coverage_view, name="leave_coverage"),
    path("leave/coverage/", leave_views.leave_coverage_view),
    path(
        "leave/coverage/<str:assignment_id>/revoke",
        leave_views.revoke_coverage_action,
        name="revoke_coverage_action",
    ),
    path("leave/calendar", leave_views.leave_calendar_view, name="leave_calendar"),
    path("leave/calendar/", leave_views.leave_calendar_view),
    # Lives under /leave/ — an "admin/…" prefix would be shadowed by the
    # Django admin site mounted at admin/ in config/urls.py.
    path("leave/policies", leave_views.leave_policies_view, name="leave_policies"),
    path("leave/policies/", leave_views.leave_policies_view),
    path("public-holidays", leave_views.public_holidays_view, name="public_holidays"),
    path("public-holidays/", leave_views.public_holidays_view),
    path(
        "leave/team-availability",
        leave_views.team_availability_view,
        name="team_availability",
    ),
    path("leave/team-availability/", leave_views.team_availability_view),
    # Country Budget
    path(
        "rvp/annual/<str:budget_id>/action",
        rvp_views.rvp_annual_action_view,
        name="rvp_annual_action",
    ),
    path(
        "rvp/project/<str:project_id>/decision",
        rvp_views.rvp_project_decision_view,
        name="rvp_project_decision",
    ),
    path(
        "rvp/strategy-note", rvp_views.rvp_strategy_note_view, name="rvp_strategy_note"
    ),
    path("rvp/approvals", rvp_views.rvp_approvals_drawer_view, name="rvp_approvals"),
    path("country-budget", finance_views.country_budget_view, name="country_budget"),
    path("country-budget/", finance_views.country_budget_view),
    path(
        "country-budget/plan-sources",
        finance_views.country_budget_plan_sources_view,
        name="country_budget_plan_sources",
    ),
    path(
        "country-budget/return",
        finance_views.country_budget_return_drawer_view,
        name="country_budget_return_drawer",
    ),
    path(
        "country-budget/action",
        finance_views.country_budget_action_view,
        name="country_budget_action",
    ),
    # My Team (PL view)
    path("my-team", staff_views.my_team_view, name="my_team"),
    # Notifications
    path(
        "notifications",
        staff_views.notifications_page_view,
        name="notifications",
    ),
    path("notifications/", staff_views.notifications_page_view),
    path(
        "notifications/drawer",
        staff_views.notification_drawer_view,
        name="notifications_drawer",
    ),
    path(
        "notifications/mark-all-read",
        staff_views.mark_all_notifications_read,
        name="mark_all_notifications_read",
    ),
    path(
        "notifications/<str:notif_id>/read",
        staff_views.mark_notification_read,
        name="mark_notif_read",
    ),
    # Profile
    path("profile", staff_views.profile_view, name="profile"),
    # ── GROUP 2: Finance ──────────────────────────────────────────────────────
    path(
        "fund-requests",
        finance_views.fund_requests_list_view,
        name="fund_requests_list",
    ),
    path("disbursements", finance_views.disbursements_view, name="disbursements"),
    path(
        "disbursements/detail",
        finance_views.disbursement_detail_view,
        name="disbursements_detail",
    ),
    path(
        "disbursements/drawer",
        finance_views.disbursement_drawer_view,
        name="disbursements_drawer",
    ),
    path(
        "disbursements/action",
        finance_views.disbursement_action_view,
        name="disbursements_action",
    ),
    path(
        "fund-requests/receipt-confirm",
        finance_views.fund_receipt_confirm_action,
        name="fund_receipt_confirm",
    ),
    path(
        "finance/actions/drawer",
        finance_views.finance_action_drawer_view,
        name="finance_action_drawer",
    ),
    path(
        "finance/actions/disburse_advance",
        finance_views.disburse_advance_action,
        name="disburse_advance_action",
    ),
    path(
        "finance/actions/clear_partner_payment",
        finance_views.clear_partner_payment_action,
        name="clear_partner_payment_action",
    ),
    path(
        "finance/actions/process_reimbursement",
        finance_views.process_reimbursement_action,
        name="process_reimbursement_action",
    ),
    path(
        "finance/actions/confirm_accountability",
        finance_views.confirm_accountability_action,
        name="confirm_accountability_action",
    ),
    path(
        "finance/actions/return_correction",
        finance_views.finance_return_action,
        name="finance_return_action",
    ),
    path(
        "budgets/overview", finance_views.budget_overview_view, name="budget_overview"
    ),
    path("cost-settings", finance_views.cost_settings_view, name="cost_settings"),
    path(
        "finance/fund-allocation",
        finance_views.fund_allocation_view,
        name="fund_allocation",
    ),
    path("finance/fund-allocation/", finance_views.fund_allocation_view),
    path(
        "finance/fund-allocation/admin-budget-drilldown",
        finance_views.admin_budget_drilldown_view,
        name="admin_budget_drilldown",
    ),
    path(
        "finance/fund-allocation/drilldown",
        finance_views.allocation_drilldown_view,
        name="allocation_drilldown",
    ),
    path(
        "finance/fund-allocation/export-drawer",
        finance_views.export_drawer_view,
        name="export_drawer",
    ),
    # ── Controlled Finance Operating System ───────────────────────────────────
    path(
        "accounts",
        finance_operating_views.accountant_dashboard_view,
        name="finance_dashboard",
    ),
    path("accounts/", finance_operating_views.accountant_dashboard_view),
    path(
        "accounts/advances",
        finance_operating_views.ready_for_advance_view,
        name="finance_ready_for_advance",
    ),
    path("accounts/advances/", finance_operating_views.ready_for_advance_view),
    path(
        "accounts/activities/<str:activity_id>/disburse",
        finance_operating_views.mark_disbursed_action,
        name="finance_mark_disbursed",
    ),
    path(
        "accounts/partner-payments",
        finance_operating_views.partner_payments_view,
        name="finance_partner_payments",
    ),
    path("accounts/partner-payments/", finance_operating_views.partner_payments_view),
    path(
        "accounts/partner-payments/<str:activity_id>/pay",
        finance_operating_views.pay_partner_action,
        name="finance_pay_partner",
    ),
    path(
        "accounts/reimbursements",
        finance_operating_views.reimbursements_view,
        name="finance_reimbursements",
    ),
    path("accounts/reimbursements/", finance_operating_views.reimbursements_view),
    path(
        "accounts/reimbursements/<str:claim_id>/pay",
        finance_operating_views.pay_reimbursement_action,
        name="finance_pay_reimbursement",
    ),
    path(
        "accounts/accountability",
        finance_operating_views.accountability_view,
        name="finance_accountability",
    ),
    path("accounts/accountability/", finance_operating_views.accountability_view),
    path(
        "accounts/activities/<str:activity_id>/netsuite-id",
        finance_operating_views.netsuite_id_action,
        name="finance_netsuite_id",
    ),
    path(
        "accounts/blocked", finance_operating_views.blocked_view, name="finance_blocked"
    ),
    path("accounts/blocked/", finance_operating_views.blocked_view),
    path(
        "accounts/variance-review",
        finance_operating_views.variance_review_view,
        name="finance_variance_review",
    ),
    path("accounts/variance-review/", finance_operating_views.variance_review_view),
    path(
        "accounts/returned",
        finance_operating_views.returned_view,
        name="finance_returned",
    ),
    path("accounts/returned/", finance_operating_views.returned_view),
    path(
        "accounts/cleared", finance_operating_views.cleared_view, name="finance_cleared"
    ),
    path("accounts/cleared/", finance_operating_views.cleared_view),
    path(
        "accounts/activities/<str:activity_id>",
        finance_operating_views.activity_finance_detail_view,
        name="finance_activity_detail",
    ),
    path(
        "accounts/activities/<str:activity_id>/",
        finance_operating_views.activity_finance_detail_view,
    ),
    path(
        "accounts/batch-payments",
        finance_operating_views.batch_payments_view,
        name="finance_batch_payments",
    ),
    path("accounts/batch-payments/", finance_operating_views.batch_payments_view),
    path(
        "accounts/approval-history",
        finance_operating_views.approval_history_view,
        name="finance_approval_history",
    ),
    path("accounts/approval-history/", finance_operating_views.approval_history_view),
    path(
        "accounts/audit-log",
        finance_operating_views.audit_log_view,
        name="finance_audit_log",
    ),
    path("accounts/audit-log/", finance_operating_views.audit_log_view),
    path(
        "accounts/monthly-request",
        finance_operating_views.monthly_request_view,
        name="finance_monthly_request",
    ),
    path("accounts/monthly-request/", finance_operating_views.monthly_request_view),
    path(
        "accounts/weekly-requests",
        finance_operating_views.weekly_requests_view,
        name="finance_weekly_requests",
    ),
    path("accounts/weekly-requests/", finance_operating_views.weekly_requests_view),
    # ── Controlled Activity Closure Workflow ──────────────────────────────────
    path(
        "activities/closure",
        closure_views.closure_readiness_queue_view,
        name="closure_readiness",
    ),
    path("activities/closure/", closure_views.closure_readiness_queue_view),
    path(
        "activities/<str:activity_id>/closure",
        closure_views.activity_closure_detail_view,
        name="activity_closure_detail",
    ),
    path(
        "activities/<str:activity_id>/closure/",
        closure_views.activity_closure_detail_view,
    ),
    path(
        "activities/<str:activity_id>/closure/close",
        closure_views.close_activity_action,
        name="close_activity",
    ),
    path(
        "completed-activities/<str:activity_id>",
        closure_views.completed_activity_detail_view,
        name="completed_activity_detail",
    ),
    path(
        "completed-activities/<str:activity_id>/",
        closure_views.completed_activity_detail_view,
    ),
    path(
        "activities/closure/blocked",
        closure_views.blocked_closure_view,
        name="blocked_closure",
    ),
    path("activities/closure/blocked/", closure_views.blocked_closure_view),
    path(
        "activities/<str:activity_id>/reopen",
        closure_views.reopen_activity_action,
        name="reopen_activity",
    ),
    path(
        "activities/<str:activity_id>/timeline",
        closure_views.activity_timeline_view,
        name="activity_timeline",
    ),
    path(
        "analytics/publishing",
        closure_views.analytics_publishing_status_view,
        name="analytics_publishing_status",
    ),
    path("analytics/publishing/", closure_views.analytics_publishing_status_view),
    # ── GROUP 3: Partners ─────────────────────────────────────────────────────
    path("partners", partner_views.partners_list_view, name="partners_list"),
    path(
        "partners/<str:partner_id>",
        partner_views.partner_detail_view,
        name="partner_detail",
    ),
    path("partner/today", partner_views.partner_today_view, name="partner_today"),
    path("partner/schools", partner_views.partner_schools_view, name="partner_schools"),
    path(
        "partner/activities",
        partner_views.partner_activities_view,
        name="partner_activities",
    ),
    path(
        "partner/evidence", partner_views.partner_evidence_view, name="partner_evidence"
    ),
    path("partner/my-plan", partner_views.partner_my_plan_view, name="partner_my_plan"),
    # ── GROUP 4: SSA, FY & Planning ──────────────────────────────────────────
    path("ssa", extended_views.ssa_master_view, name="ssa_master"),
    path("fy", extended_views.fy_overview_view, name="fy_overview"),
    path("calendar", extended_views.calendar_view, name="calendar"),
    path("work-plan", extended_views.work_plan_view, name="work_plan"),
    # ── GROUP 5: Districts, Reports & Coverage ────────────────────────────────
    path("districts", extended_views.districts_list_view, name="districts_list"),
    path(
        "districts/<str:district_id>",
        extended_views.district_detail_view,
        name="district_detail",
    ),
    path("reports", extended_views.reports_view, name="reports"),
    path("coverage", extended_views.coverage_view, name="coverage"),
    # ── GROUP 6: Admin, Settings, Messages, Leaves & Search ───────────────────
    path("admin-panel", extended_views.admin_panel_view, name="admin_panel"),
    path("admin-panel/users", extended_views.admin_users_view, name="admin_users"),
    path(
        "admin-panel/users/<str:user_id>",
        extended_views.admin_user_detail_view,
        name="admin_user_detail",
    ),
    path("admin-panel/audit-log", extended_views.audit_log_view, name="audit_log"),
    path(
        "admin-panel/roles-permissions",
        extended_views.admin_roles_permissions_view,
        name="admin_roles_permissions",
    ),
    path(
        "admin-panel/staff-setup-queue",
        extended_views.admin_staff_setup_queue_view,
        name="admin_staff_setup_queue",
    ),
    path(
        "admin-panel/school-upload-history",
        extended_views.admin_school_upload_history_view,
        name="admin_school_upload_history",
    ),
    path(
        "admin-panel/data-quality-center",
        extended_views.admin_data_quality_center_view,
        name="admin_data_quality_center",
    ),
    path(
        "data-quality/duplicates",
        extended_views.duplicate_review_view,
        name="duplicate_review",
    ),
    path(
        "data-quality/issue/<str:issue_id>/action",
        extended_views.data_quality_issue_action_view,
        name="data_quality_issue_action",
    ),
    path("ssa/upload/", ssa_views.ssa_upload_center_view, name="ssa_upload_center"),
    path(
        "ssa/upload/template",
        ssa_views.ssa_template_download_view,
        name="ssa_template_download",
    ),
    path(
        "ssa/upload/<str:batch_id>/preview/",
        ssa_views.ssa_upload_preview_view,
        name="ssa_upload_preview",
    ),
    path(
        "ssa/upload/<str:batch_id>/result/",
        ssa_views.ssa_upload_result_view,
        name="ssa_upload_result",
    ),
    path(
        "ssa/verification/",
        ssa_views.ssa_verification_queue_view,
        name="ssa_verification_queue",
    ),
    path(
        "ssa/unmatched",
        extended_views.unmatched_ssa_queue_view,
        name="unmatched_ssa_queue",
    ),
    path(
        "admin-panel/workflow-rules",
        extended_views.admin_workflow_rules_view,
        name="admin_workflow_rules",
    ),
    path(
        "admin-panel/page-access-matrix",
        extended_views.admin_page_access_matrix_view,
        name="admin_page_access_matrix",
    ),
    path(
        "admin-panel/region-district-setup",
        extended_views.admin_region_district_setup_view,
        name="admin_region_district_setup",
    ),
    path(
        "admin-panel/notifications-mgmt",
        extended_views.admin_notifications_mgmt_view,
        name="admin_notifications_mgmt",
    ),
    path("settings", extended_views.settings_view, name="settings"),
    path("search", extended_views.search_view, name="search"),
    path("messages", message_views.messages_list_view, name="messages_list"),
    path("messages/", message_views.messages_list_view),
    path("messages/new", message_views.message_compose_view, name="message_compose"),
    path("messages/new/", message_views.message_compose_view),
    path(
        "messages/new/records",
        message_views.compose_records_partial,
        name="message_compose_records",
    ),
    path(
        "messages/new/suggestions",
        message_views.compose_suggestions_partial,
        name="message_compose_suggestions",
    ),
    path(
        "messages/new/summary",
        message_views.compose_summary_partial,
        name="message_compose_summary",
    ),
    path(
        "messages/thread/<str:thread_id>",
        message_views.thread_view,
        name="message_thread",
    ),
    path(
        "messages/thread/<str:thread_id>/reply",
        message_views.thread_reply_action,
        name="message_thread_reply",
    ),
    path(
        "messages/thread/<str:thread_id>/archive",
        message_views.thread_archive_action,
        name="message_thread_archive",
    ),
    path(
        "messages/thread/<str:thread_id>/star",
        message_views.thread_star_action,
        name="message_thread_star",
    ),
    path(
        "messages/<str:message_id>",
        message_views.message_deep_link_view,
        name="message_detail",
    ),
    path("leave-requests", extended_views.leave_requests_view, name="leave_requests"),
    path("map", extended_views.map_view, name="map"),
    # ── GROUP 7: Core Schools, Projects, Debriefs, Completed, Quality, Help ───
    path("core-schools", core_schools_views.core_schools_view, name="core_schools"),
    path(
        "core-schools/schedule-visit",
        core_schools_views.core_schedule_visit_drawer,
        name="core_schedule_visit_drawer",
    ),
    path(
        "core-schools/schedule-visit/action",
        core_schools_views.core_schedule_visit_action,
        name="core_schedule_visit_action",
    ),
    path(
        "core-schools/schedule-training",
        core_schools_views.core_schedule_training_drawer,
        name="core_schedule_training_drawer",
    ),
    path(
        "core-schools/schedule-training/action",
        core_schools_views.core_schedule_training_action,
        name="core_schedule_training_action",
    ),
    path(
        "core-schools/assign-partner",
        core_schools_views.core_assign_partner_drawer,
        name="core_assign_partner_drawer",
    ),
    path(
        "core-schools/assign-partner/action",
        core_schools_views.core_assign_partner_action,
        name="core_assign_partner_action",
    ),
    path(
        "core-schools/assessment",
        core_schools_views.core_assessment_drawer,
        name="core_assessment_drawer",
    ),
    path(
        "core-schools/strategy-playbook",
        core_schools_views.core_strategy_playbook_drawer,
        name="core_strategy_playbook_drawer",
    ),
    # Literal champion routes MUST precede the catch-all <plan_id> route,
    # otherwise /core-schools/champions resolves as a plan detail.
    path(
        "core-schools/champion-candidates",
        core_schools_views.champion_candidates_view,
        name="champion_candidates",
    ),
    path(
        "core-schools/champions",
        core_schools_views.champions_list_view,
        name="champions_list",
    ),
    path(
        "core-schools/<str:school_id>/champion-review",
        core_schools_views.champion_review_drawer,
        name="champion_review_drawer",
    ),
    path(
        "core-schools/<str:school_id>/champion-approve",
        core_schools_views.champion_approve_action,
        name="champion_approve_action",
    ),
    path(
        "core-schools/<str:school_id>/champion-reject",
        core_schools_views.champion_reject_action,
        name="champion_reject_action",
    ),
    path(
        "core-schools/<str:plan_id>",
        extended_views.core_school_detail_view,
        name="core_school_detail",
    ),
    path("projects", extended_views.projects_list_view, name="projects_list"),
    path(
        "projects/analytics",
        extended_views.special_projects_analytics_view,
        name="special_projects_analytics",
    ),
    path(
        "projects/planning",
        extended_views.special_projects_planning_view,
        name="special_projects_planning",
    ),
    path(
        "projects/my-plan",
        extended_views.special_projects_my_plan_view,
        name="special_projects_my_plan",
    ),
    path(
        "projects/<str:project_id>",
        extended_views.project_detail_view,
        name="project_detail",
    ),
    path("debriefs", debrief_views.field_debrief_dashboard_view, name="debriefs_list"),
    path(
        "debriefs/submit",
        debrief_views.field_debrief_submit_view,
        name="debrief_submit",
    ),
    path(
        "debriefs/action",
        debrief_views.field_debrief_action_view,
        name="debrief_action",
    ),
    path(
        "debriefs/activity-options",
        debrief_views.field_debrief_activity_options_view,
        name="debrief_activity_options",
    ),
    path(
        "debriefs/<str:debrief_id>",
        debrief_views.field_debrief_detail_view,
        name="debrief_detail",
    ),
    path(
        "completed-activities",
        closure_views.completed_activities_view,
        name="completed_activities",
    ),
    path("quality-checks", extended_views.quality_checks_view, name="quality_checks"),
    path("help", extended_views.help_view, name="help"),
    # Cost catalogue inline row edits
    path(
        "cost-settings/row/<str:key>",
        finance_views.cost_setting_row_view,
        name="cost_setting_row",
    ),
    path(
        "cost-settings/initialize-default",
        finance_views.initialize_default_catalogue_view,
        name="initialize_default_catalogue",
    ),
    # HCOS routes
    path("org-structure", hr_views.org_structure_view, name="org_structure"),
    path(
        "workforce-planning",
        hr_views.workforce_planning_view,
        name="workforce_planning",
    ),
    path("recruitment", hr_views.recruitment_view, name="recruitment"),
    path(
        "candidate-pipeline",
        hr_views.candidate_pipeline_view,
        name="candidate_pipeline",
    ),
    path("onboarding", hr_views.onboarding_view, name="onboarding"),
    path("cpd-learning", hr_views.cpd_learning_view, name="cpd_learning"),
    path(
        "cpd-learning/adjust-allocation",
        hr_views.pd_dashboard_adjust_allocation_view,
        name="pd_dashboard_adjust_allocation",
    ),
    path(
        "cpd-learning/action",
        hr_views.pd_dashboard_action_view,
        name="pd_dashboard_action",
    ),
    path(
        "succession-planning",
        hr_views.succession_planning_view,
        name="succession_planning",
    ),
    path(
        "performance-reviews",
        hr_views.performance_reviews_view,
        name="performance_reviews",
    ),
    path("recovery-plans", hr_views.recovery_plans_view, name="recovery_plans"),
    path(
        "culture-engagement",
        hr_views.culture_engagement_view,
        name="culture_engagement",
    ),
    path(
        "employee-relations",
        hr_views.employee_relations_view,
        name="employee_relations",
    ),
    path("wellness", hr_views.wellness_view, name="wellness"),
    path(
        "compensation-benefits",
        hr_views.compensation_benefits_view,
        name="compensation_benefits",
    ),
    path(
        "payroll-readiness", hr_views.payroll_readiness_view, name="payroll_readiness"
    ),
    path(
        "compliance-register",
        hr_views.compliance_register_view,
        name="compliance_register",
    ),
    path("policies", hr_views.policies_view, name="policies"),
    path("offboarding", hr_views.offboarding_view, name="offboarding"),
    path("hr-analytics", hr_views.hr_analytics_view, name="hr_analytics"),
    path("hr-audit-log", hr_views.hr_audit_log_view, name="hr_audit_log"),
    # Root redirects to dashboard (which handles auth redirect)
    path("", dashboard_views.dashboard_view, name="index"),
]
