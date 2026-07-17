# Edify Platform Page Inventory

Generated from the live Django URL resolver, role permissions, navigation, view source and templates.

## Summary

- Routed product surfaces: **374**
- All registered routes: **950**
- API routes: **528**
- Roles: **11**
- Permission keys: **39**
- Scheduled jobs: **8**
- Activity states: **23**
- Shared component templates: **232**
- Full pages: **236**
- Partials and drawers: **128**
- Permission-gated surfaces: **372**
- Referenced by automated tests: **334**
- Findings: critical **0**, high **0**, medium **0**, low **0**

> Automated scores are provisional evidence derived from explicit findings and state coverage. A page is not complete until manual visual, responsive and accessibility scores are recorded.

## Routed surfaces

| Route | Page | Roles | Template | Automated score | Findings | Test |
|---|---|---|---|---:|---:|---|
| / | Country Director Dashboard · Edify | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/dashboards/cd/body.html<br>pages/dashboards/cd.html<br>partials/dashboards/pl/body.html<br>pages/dashboards/pl.html<br>pages/dashboards/rvp.html<br>partials/dashboards/hr/body.html<br>pages/dashboards/hr.html<br>pages/dashboards/cceo.html<br>pages/dashboards/special_projects.html<br>pages/dashboards/main.html | 9.7 | 0 | referenced by automated test |
| /accounts | Fund Disbursement Dashboard | ACCOUNTANT, ADMIN | pages/accounts/dashboard.html | 9.6 | 0 | referenced by automated test |
| /accounts/ | Fund Disbursement Dashboard | ACCOUNTANT, ADMIN | pages/accounts/dashboard.html | 9.6 | 0 | referenced by automated test |
| /accounts/accountability | Accountability Tracking - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/accountability.html | 9.4 | 0 | referenced by automated test |
| /accounts/accountability/ | Accountability Tracking - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/accountability.html | 9.4 | 0 | referenced by automated test |
| /accounts/activities/<str:activity_id> | Activity Finance Detail - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/activity_finance_detail.html | 9.7 | 0 | referenced by automated test |
| /accounts/activities/<str:activity_id>/ | Activity Finance Detail - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/activity_finance_detail.html | 9.7 | 0 | referenced by automated test |
| /accounts/activities/<str:activity_id>/disburse | Finance Mark Disbursed | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /accounts/activities/<str:activity_id>/netsuite-id | Finance Netsuite Id | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /accounts/activity-evidence/<str:activity_id> | Activity Evidence Review | ACCOUNTANT, ADMIN | pages/accounts/activity_evidence.html | 9.4 | 0 | referenced by automated test |
| /accounts/advances | Advances Queue - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/ready_for_advance.html | 9.4 | 0 | referenced by automated test |
| /accounts/advances/ | Advances Queue - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/ready_for_advance.html | 9.4 | 0 | referenced by automated test |
| /accounts/approval-history | Approval History - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/approval_history.html | 9.4 | 0 | referenced by automated test |
| /accounts/approval-history/ | Approval History - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/approval_history.html | 9.4 | 0 | referenced by automated test |
| /accounts/audit-log | Finance Audit Log - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/audit_log.html | 9.4 | 0 | referenced by automated test |
| /accounts/audit-log/ | Finance Audit Log - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/audit_log.html | 9.4 | 0 | referenced by automated test |
| /accounts/batch-payments | Batch Payments - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/batch_payments.html | 9.6 | 0 | referenced by automated test |
| /accounts/batch-payments/ | Batch Payments - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/batch_payments.html | 9.6 | 0 | referenced by automated test |
| /accounts/blocked | Blocked Items - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/blocked.html | 9.4 | 0 | referenced by automated test |
| /accounts/blocked/ | Blocked Items - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/blocked.html | 9.4 | 0 | referenced by automated test |
| /accounts/budget-amendments | Budget Amendments · Edify | ACCOUNTANT, ADMIN | pages/accounts/budget_amendments.html | 9.4 | 0 | referenced by automated test |
| /accounts/budget-amendments/<str:amendment_id>/action | Budget Amendment Action | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /accounts/cleared | Cleared Ledger - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/cleared.html | 9.4 | 0 | referenced by automated test |
| /accounts/cleared/ | Cleared Ledger - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/cleared.html | 9.4 | 0 | referenced by automated test |
| /accounts/monthly-request | Monthly Fund Request - Edify Command Center | ACCOUNTANT, ADMIN, CD, IA, PL, PROJECT_COORDINATOR, RVP | pages/accounts/monthly_request.html | 9.4 | 0 | coverage review required |
| /accounts/monthly-request/ | Monthly Fund Request - Edify Command Center | ACCOUNTANT, ADMIN, CD, IA, PL, PROJECT_COORDINATOR, RVP | pages/accounts/monthly_request.html | 9.4 | 0 | coverage review required |
| /accounts/partner-payments | Partner Payments - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/partner_payments.html | 9.4 | 0 | referenced by automated test |
| /accounts/partner-payments/ | Partner Payments - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/partner_payments.html | 9.4 | 0 | referenced by automated test |
| /accounts/partner-payments/<str:activity_id>/pay | Finance Pay Partner | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /accounts/reimbursements | Reimbursements Queue - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/reimbursements.html | 9.4 | 0 | referenced by automated test |
| /accounts/reimbursements/ | Reimbursements Queue - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/reimbursements.html | 9.4 | 0 | referenced by automated test |
| /accounts/reimbursements/<str:claim_id>/pay | Finance Pay Reimbursement | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /accounts/returned | Returned Items - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/returned.html | 9.4 | 0 | referenced by automated test |
| /accounts/returned/ | Returned Items - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/returned.html | 9.4 | 0 | referenced by automated test |
| /accounts/variance-review | Variance Review - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/variance_review.html | 9.6 | 0 | referenced by automated test |
| /accounts/variance-review/ | Variance Review - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/variance_review.html | 9.6 | 0 | referenced by automated test |
| /accounts/weekly-requests | Weekly Fund Requests - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/weekly_requests.html | 9.4 | 0 | referenced by automated test |
| /accounts/weekly-requests/ | Weekly Fund Requests - Edify Command Center | ACCOUNTANT, ADMIN | pages/accounts/weekly_requests.html | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id> | Activity Details | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/activity_detail_drawer.html<br>pages/my_plan/detail.html | 9.6 | 0 | referenced by automated test |
| /activities/<str:activity_id>/attendance | Attendance Upload Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/attendance_drawer.html | 9.6 | 0 | referenced by automated test |
| /activities/<str:activity_id>/attendance/action | Attendance Upload Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/closure | Closure Workspace - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/activity_closure_detail.html | 9.7 | 0 | referenced by automated test |
| /activities/<str:activity_id>/closure/ | Closure Workspace - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/activity_closure_detail.html | 9.7 | 0 | referenced by automated test |
| /activities/<str:activity_id>/closure/close | Close Activity | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/complete | Complete Activity Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/complete/action | Complete Activity Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/evidence | Evidence Upload Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/evidence_drawer.html | 9.6 | 0 | referenced by automated test |
| /activities/<str:activity_id>/evidence/action | Evidence Upload Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/evidence/detail | Evidence Packet | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | pages/my_plan/evidence_packet.html | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/reopen | Reopen Activity | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/salesforce-id | Salesforce Id Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/salesforce_id_drawer.html | 9.6 | 0 | referenced by automated test |
| /activities/<str:activity_id>/salesforce-id/action | Salesforce Id Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/ssa-upload | Ssa Evidence Upload Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/ssa_upload_drawer.html | 9.6 | 0 | referenced by automated test |
| /activities/<str:activity_id>/ssa-upload/action | Ssa Evidence Upload Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/start | Start Activity Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/start_drawer.html | 9.6 | 0 | referenced by automated test |
| /activities/<str:activity_id>/start/action | Start Activity Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/submit | Submit For Review Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/submit_drawer.html | 9.7 | 0 | referenced by automated test |
| /activities/<str:activity_id>/submit/action | Submit For Review Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/timeline | Activity Timeline Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/timeline_drawer.html | 9.4 | 0 | referenced by automated test |
| /activities/<str:activity_id>/timeline | Activity Journey Timeline - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/activity_timeline.html | 9.6 | 0 | referenced by automated test |
| /activities/<str:activity_id>/timeline/ | Activity Timeline - Edify Command Center | ADMIN | pages/ia/activity_timeline.html | 9.6 | 0 | coverage review required |
| /activities/closure | Activity Closure Center - Edify | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/readiness_queue.html | 9.6 | 0 | referenced by automated test |
| /activities/closure/ | Activity Closure Center - Edify | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/readiness_queue.html | 9.6 | 0 | referenced by automated test |
| /activities/closure/blocked | Blocked Closures - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/blocked_closure.html | 9.4 | 0 | referenced by automated test |
| /activities/closure/blocked/ | Blocked Closures - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/blocked_closure.html | 9.4 | 0 | referenced by automated test |
| /admin-panel | Admin Dashboard | ADMIN | pages/admin/index.html | 9.4 | 0 | referenced by automated test |
| /admin-panel/audit-log | Audit Log | ADMIN | pages/admin/audit_log.html | 9.4 | 0 | referenced by automated test |
| /admin-panel/data-quality-center | Data Quality Center | ADMIN, IA | pages/admin/data_quality_center.html | 9.4 | 0 | referenced by automated test |
| /admin-panel/notifications-mgmt | Notification Logs | ADMIN | pages/admin/notifications_mgmt.html | 9.7 | 0 | referenced by automated test |
| /admin-panel/page-access-matrix | Access Matrix | ADMIN | pages/admin/page_access_matrix.html | 9.6 | 0 | referenced by automated test |
| /admin-panel/region-district-setup | District Setup | ADMIN | pages/admin/region_district_setup.html | 9.6 | 0 | referenced by automated test |
| /admin-panel/roles-permissions | Roles & Permissions | ADMIN | pages/admin/roles_permissions.html | 9.6 | 0 | referenced by automated test |
| /admin-panel/school-upload-history | Upload History | ADMIN, IA | pages/admin/school_upload_history.html | 9.7 | 0 | referenced by automated test |
| /admin-panel/staff-setup-queue | Staff Setup Queue | ADMIN, CD, HR | pages/admin/staff_setup_queue.html | 9.6 | 0 | referenced by automated test |
| /admin-panel/users | User Management | ADMIN, CD, HR | pages/admin/users.html | 9.7 | 0 | referenced by automated test |
| /admin-panel/users/<str:user_id> | Manage User: | ADMIN, CD, HR | pages/admin/user_detail.html | 9.7 | 0 | referenced by automated test |
| /admin-panel/workflow-rules | Workflow Rules | ADMIN | pages/admin/workflow_rules.html | 9.4 | 0 | referenced by automated test |
| /analytics | Analytics | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/analytics/kpi_cards.html<br>pages/analytics/index.html | 9.4 | 0 | referenced by automated test |
| /analytics/ | Analytics | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/analytics/kpi_cards.html<br>pages/analytics/index.html | 9.4 | 0 | referenced by automated test |
| /analytics/country-director | Analytics | ADMIN, CD | partials/analytics/cd/body.html<br>pages/analytics/cd_analytics.html | 9.4 | 0 | referenced by automated test |
| /analytics/country-director/drilldown | Cd Analytics Drilldown | ADMIN, CD | partials/analytics/cd/drilldown.html | 9.6 | 0 | referenced by automated test |
| /analytics/country-director/export | Cd Analytics Export | ADMIN, CD | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /analytics/customize-dashboard | Analytics Customize Dashboard | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/schools/toast_success.html<br>partials/analytics/customize_dashboard_drawer.html | 9.6 | 0 | referenced by automated test |
| /analytics/drilldown | Analytics Drilldown | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/analytics/drilldown_drawer.html | 9.4 | 0 | referenced by automated test |
| /analytics/export | Analytics Export | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /analytics/program-lead | Analytics | ADMIN, PL | partials/analytics/pl/body.html<br>pages/analytics/pl_analytics.html | 9.4 | 0 | referenced by automated test |
| /analytics/program-lead/drilldown | Pl Analytics Drilldown | ADMIN, PL | partials/analytics/pl/drilldown.html | 9.4 | 0 | referenced by automated test |
| /analytics/program-lead/export | Pl Analytics Export | ADMIN, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /analytics/publishing | Analytics Publishing Status - Edify Command Center | ADMIN, CD, IA | pages/analytics/publishing_status.html | 9.7 | 0 | coverage review required |
| /analytics/publishing/ | Analytics Publishing Status - Edify Command Center | ADMIN, CD, IA | pages/analytics/publishing_status.html | 9.7 | 0 | coverage review required |
| /analytics/schedule-report | Analytics Schedule Report | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/schools/toast_success.html<br>partials/analytics/schedule_report_drawer.html | 9.6 | 0 | referenced by automated test |
| /budgets/monthly | Monthly Fund Request - Edify Command Center | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | pages/budgets/monthly.html | 9.6 | 0 | referenced by automated test |
| /budgets/overview | Budget Overview | ACCOUNTANT, ADMIN, CD, IA, RVP | pages/budget/index.html | 9.4 | 0 | coverage review required |
| /calendar | Calendar | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/calendar/index.html | 9.6 | 0 | referenced by automated test |
| /candidate-pipeline | Candidate Pipeline | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /change-password | Change Password | Unmapped | pages/auth/change_password.html | 9.6 | 0 | referenced by automated test |
| /clusters | Clusters | ADMIN, CCEO, CD, IA, PARTNER, PL | partials/clusters/htmx_response.html<br>pages/clusters/index.html | 9.6 | 0 | referenced by automated test |
| /clusters/<str:cluster_id> | Cluster details | ADMIN, CCEO, CD, IA, PARTNER, PL | pages/clusters/detail.html | 9.4 | 0 | referenced by automated test |
| /clusters/<str:cluster_id>/bulk-assign-drawer | Cluster Bulk Assign Drawer | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/schools/toast_success.html<br>partials/clusters/bulk_assign_drawer.html | 9.6 | 0 | referenced by automated test |
| /clusters/<str:cluster_id>/edit | Edit Cluster | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /clusters/<str:cluster_id>/edit-drawer | Edit Cluster Drawer | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/clusters/edit_cluster_drawer.html | 9.4 | 0 | referenced by automated test |
| /clusters/cost-preview | Cluster Cost Preview | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/cost_preview.html | 9.6 | 0 | referenced by automated test |
| /clusters/create | Create Cluster | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /clusters/create-drawer | Create Cluster Drawer | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/clusters/create_cluster_drawer.html | 9.4 | 0 | referenced by automated test |
| /clusters/detail-drawer/<str:cluster_id> | Cluster Detail Drawer | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/clusters/cluster_detail_drawer.html | 9.4 | 0 | referenced by automated test |
| /clusters/eligible-staff | Eligible Staff Options | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /clusters/impact-drawer/<str:cluster_id> | Cluster Impact Drawer | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/clusters/intervention_impact_drawer.html | 9.4 | 0 | referenced by automated test |
| /clusters/impact/<str:cluster_id> | Cluster Impact Partial | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/clusters/impact_panel.html | 9.4 | 0 | referenced by automated test |
| /clusters/planner-drawer | Cluster Planner Drawer | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/clusters/cluster_action_planner_drawer.html | 9.8 | 0 | referenced by automated test |
| /clusters/schedule-activity | Cluster Schedule Activity | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/clusters/cluster_action_planner_drawer.html | 9.8 | 0 | referenced by automated test |
| /clusters/schedule-meeting-drawer | Schedule Meeting Drawer | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /clusters/schedule-training-drawer | Schedule Training Drawer | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /compensation-benefits | Compensation & Benefits | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /completed-activities | Completed Archive - Edify Command Center | ADMIN, CCEO, IA, PL, PROJECT_COORDINATOR | pages/closure/completed_activities.html | 9.4 | 0 | coverage review required |
| /completed-activities/<str:activity_id> | Completed Activity Record - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/completed_detail.html | 9.4 | 0 | referenced by automated test |
| /completed-activities/<str:activity_id>/ | Completed Activity Record - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/closure/completed_detail.html | 9.4 | 0 | referenced by automated test |
| /compliance-register | Compliance Register | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /core-schools | Core Schools | ADMIN, CCEO, IA, PL | partials/core_schools/matrix_table.html<br>pages/core_schools/index.html | 9.4 | 0 | referenced by automated test |
| /core-schools/<str:plan_id> | Core School Plan | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/core_schools/detail.html | 9.4 | 0 | referenced by automated test |
| /core-schools/<str:school_id>/champion-approve | Champion Approve Action | ADMIN, CCEO, IA, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /core-schools/<str:school_id>/champion-reject | Champion Reject Action | ADMIN, CCEO, IA, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /core-schools/<str:school_id>/champion-review | Champion Review Drawer | ADMIN, CCEO, IA, PL | partials/core_schools/champion_review_drawer.html | 9.6 | 0 | referenced by automated test |
| /core-schools/assessment | Core Assessment Drawer | ADMIN, CCEO, IA, PL | partials/core_schools/core_assessment_drawer.html | 9.6 | 0 | referenced by automated test |
| /core-schools/assign-partner | Core Assign Partner Drawer | ADMIN, CCEO, IA, PL | partials/core_schools/assign_partner_drawer.html | 9.6 | 0 | referenced by automated test |
| /core-schools/assign-partner/action | Core Assign Partner Action | ADMIN, CCEO, IA, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /core-schools/champion-candidates | Champion School Candidates | ADMIN, CCEO, IA, PL | pages/core_schools/champion_candidates.html | 9.6 | 0 | referenced by automated test |
| /core-schools/champions | Graduated Champion Schools | ADMIN, CCEO, IA, PL | pages/core_schools/champions.html | 9.6 | 0 | referenced by automated test |
| /core-schools/schedule-training | Core Schedule Training Drawer | ADMIN, CCEO, IA, PL | partials/core_schools/schedule_training_drawer.html | 9.6 | 0 | referenced by automated test |
| /core-schools/schedule-training/action | Core Schedule Training Action | ADMIN, CCEO, IA, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /core-schools/schedule-visit | Core Schedule Visit Drawer | ADMIN, CCEO, IA, PL | partials/core_schools/schedule_visit_drawer.html | 9.6 | 0 | referenced by automated test |
| /core-schools/schedule-visit/action | Core Schedule Visit Action | ADMIN, CCEO, IA, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /core-schools/strategy-playbook | Core Strategy Playbook Drawer | ADMIN, CCEO, IA, PL | partials/core_schools/strategy_playbook_drawer.html | 9.4 | 0 | referenced by automated test |
| /cost-settings | Cost Catalogue | ADMIN, CD | pages/cost_settings/index.html | 9.6 | 0 | referenced by automated test |
| /cost-settings/initialize-default | Initialize Default Catalogue | ADMIN, CD | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /cost-settings/row/<str:key> | Cost Setting Row | ADMIN, CD | partials/cost_settings/cost_setting_row.html | 9.4 | 0 | referenced by automated test |
| /country-budget | Country Budget | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/country_budget/root.html<br>pages/finance/country_budget.html | 9.8 | 0 | referenced by automated test |
| /country-budget/ | Country Budget | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/country_budget/root.html<br>pages/finance/country_budget.html | 9.8 | 0 | referenced by automated test |
| /country-budget/action | Country Monthly Budget | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/country_budget/root.html | 9.8 | 0 | referenced by automated test |
| /country-budget/plan-sources | Country Budget Plan Sources | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/country_budget/plan_sources_drawer.html | 9.6 | 0 | referenced by automated test |
| /country-budget/return | Country Budget Return Drawer | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/country_budget/return_drawer.html | 9.4 | 0 | referenced by automated test |
| /coverage | Coverage · Edify | ADMIN, CD, HR, PL, PROJECT_COORDINATOR, RVP | pages/coverage/index.html | 9.4 | 0 | referenced by automated test |
| /cpd-learning | CPD & Learning | ADMIN, CD, HR, PL | partials/hr/pd_dashboard/tracker_table.html<br>partials/hr/pd_dashboard/body.html<br>pages/hr/professional_development_dashboard.html | 9.8 | 0 | referenced by automated test |
| /cpd-learning/action | Pd Dashboard Action | ADMIN, CD, HR, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /cpd-learning/adjust-allocation | Pd Dashboard Adjust Allocation | ADMIN, CD, HR, PL | partials/hr/pd_dashboard/adjust_allocation_drawer.html | 9.4 | 0 | referenced by automated test |
| /culture-engagement | Culture & Engagement | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /dashboard | Dashboard | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/dashboards/cd/body.html<br>pages/dashboards/cd.html<br>partials/dashboards/pl/body.html<br>pages/dashboards/pl.html<br>pages/dashboards/rvp.html<br>partials/dashboards/hr/body.html<br>pages/dashboards/hr.html<br>pages/dashboards/cceo.html<br>pages/dashboards/special_projects.html<br>pages/dashboards/main.html | 9.7 | 0 | referenced by automated test |
| /dashboard/cd-approve | Cd Dashboard Approve | ADMIN, CD | partials/dashboards/cd/body.html | 9.7 | 0 | referenced by automated test |
| /dashboard/pl-approve | Pl Dashboard Approve | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/dashboards/pl/body.html | 9.4 | 0 | referenced by automated test |
| /dashboard/pl-drilldown | Pl Dashboard Drilldown | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/dashboards/pl/drilldown.html | 9.6 | 0 | referenced by automated test |
| /dashboard/pl-send-urgent-action | Pl Send Urgent Action | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/dashboards/pl/urgent_action_sent.html | 9.4 | 0 | referenced by automated test |
| /data-quality/duplicates | Duplicate Review | ADMIN, IA | pages/admin/duplicate_review.html | 9.6 | 0 | referenced by automated test |
| /data-quality/issue/<str:issue_id>/action | Data Quality Issue Action | ADMIN, IA | partials/data_quality/issue_row.html | 9.4 | 0 | referenced by automated test |
| /debriefs | Field Debrief | ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/debriefs/dashboard_table.html<br>partials/debriefs/dashboard_body.html<br>pages/debriefs/dashboard.html | 9.8 | 0 | referenced by automated test |
| /debriefs/<str:debrief_id> | · Field Debrief · Edify | ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/debriefs/detail.html | 9.7 | 0 | coverage review required |
| /debriefs/action | Debrief Action | ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /debriefs/activity-options | Debrief Activity Options | ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /debriefs/submit | New Field Debrief · Edify | ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/debriefs/submit.html | 9.7 | 0 | referenced by automated test |
| /disbursements | Fund Disbursement Dashboard | ACCOUNTANT, ADMIN | partials/disbursements/root.html<br>pages/disbursements/index.html | 9.7 | 0 | referenced by automated test |
| /disbursements/action | Fund Disbursement Dashboard | ACCOUNTANT, ADMIN | partials/disbursements/root.html | 9.7 | 0 | referenced by automated test |
| /disbursements/detail | Disbursements Detail | ACCOUNTANT, ADMIN | partials/disbursements/detail.html | 9.6 | 0 | referenced by automated test |
| /disbursements/drawer | Disbursements Drawer | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /districts | Districts | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/districts/index.html | 9.4 | 0 | referenced by automated test |
| /districts/<str:district_id> | District | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/districts/detail.html | 9.4 | 0 | referenced by automated test |
| /employee-relations | Employee Relations | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /evidence | Evidence Gallery | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /evidence/ | Evidence Center | ADMIN, CCEO, CD, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /evidence/returned | Returned Evidence | ADMIN, CCEO, CD, PARTNER, PL, PROJECT_COORDINATOR | pages/evidence/returned.html | 9.4 | 0 | referenced by automated test |
| /finance/actions/clear_partner_payment | Clear Partner Payment Action | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /finance/actions/confirm_accountability | Confirm Accountability Action | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /finance/actions/disburse_advance | Disburse Advance Action | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /finance/actions/drawer | Finance Action Drawer | ACCOUNTANT, ADMIN | partials/finance/finance_action_drawer.html | 9.6 | 0 | referenced by automated test |
| /finance/actions/process_reimbursement | Process Reimbursement Action | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /finance/actions/return_correction | Finance Return Action | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /finance/fund-allocation | Consolidated Fund Allocation | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/fund_allocation_table.html<br>pages/finance/fund_allocation.html | 9.4 | 0 | referenced by automated test |
| /finance/fund-allocation/ | Consolidated Fund Allocation | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/fund_allocation_table.html<br>pages/finance/fund_allocation.html | 9.4 | 0 | referenced by automated test |
| /finance/fund-allocation/admin-budget-drilldown | Admin Budget Drilldown | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/admin_budget_drilldown.html | 9.4 | 0 | referenced by automated test |
| /finance/fund-allocation/drilldown | Allocation Drilldown | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/allocation_drilldown_drawer.html | 9.4 | 0 | coverage review required |
| /finance/fund-allocation/export-drawer | Export Drawer | ACCOUNTANT, ADMIN, CD, IA, RVP | partials/finance/export_drawer.html | 9.4 | 0 | referenced by automated test |
| /fund-approvals | Fund Approvals | ADMIN, PL | partials/fund_approvals/root.html<br>pages/fund_approvals/index.html | 9.7 | 0 | referenced by automated test |
| /fund-approvals/action | Fund Approvals | ADMIN, PL | partials/fund_approvals/root.html | 9.7 | 0 | referenced by automated test |
| /fund-approvals/detail | Fund Approvals Detail | ADMIN, PL | partials/fund_approvals/detail.html | 9.7 | 0 | referenced by automated test |
| /fund-approvals/return | Fund Approvals Return | ADMIN, PL | partials/fund_approvals/return_drawer.html | 9.4 | 0 | referenced by automated test |
| /fund-requests | Fund Requests List | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /fund-requests/generate-request | Generate Request Action | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /fund-requests/receipt-confirm | Fund Receipt Confirm | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /fund-requests/weekly | Weekly Fund Request | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | partials/fund_requests/root.html<br>pages/fund_requests/weekly.html | 9.6 | 0 | referenced by automated test |
| /fund-requests/weekly/<str:request_id> | Weekly Request details - Edify Command Center | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | pages/fund_requests/detail.html | 9.4 | 0 | referenced by automated test |
| /fund-requests/weekly/<str:request_id>/approve | Fund Requests | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | partials/fund_requests/root.html<br>pages/fund_requests/weekly.html | 9.6 | 0 | referenced by automated test |
| /fund-requests/weekly/<str:request_id>/confirm | Fund Requests | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | partials/fund_requests/root.html<br>pages/fund_requests/weekly.html | 9.6 | 0 | referenced by automated test |
| /fund-requests/weekly/<str:request_id>/disburse | Weekly Fund Request Disburse | ACCOUNTANT, ADMIN | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /fund-requests/weekly/<str:request_id>/return | Fund Requests | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | partials/fund_requests/root.html<br>pages/fund_requests/weekly.html | 9.6 | 0 | referenced by automated test |
| /fund-requests/weekly/<str:request_id>/self-funded | Fund Requests | ACCOUNTANT, ADMIN, CCEO, CD, IA, PL | partials/fund_requests/root.html<br>pages/fund_requests/weekly.html | 9.6 | 0 | referenced by automated test |
| /fy | Fiscal Year Overview | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/fy/index.html | 9.4 | 0 | referenced by automated test |
| /help | Help Center · Edify | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/help/index.html | 9.6 | 0 | referenced by automated test |
| /hr-analytics | HR Analytics | ADMIN, CD, HR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /hr-audit-log | HR Audit Log | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /ia/compare/ | Evidence Comparison Workspace - Edify Command Center | ADMIN, IA | pages/ia/compare_evidence.html | 9.6 | 0 | coverage review required |
| /ia/dashboard/ | IA Quality Analytics - SIPA | ADMIN | pages/ia/analytics_dashboard.html | 9.7 | 0 | referenced by automated test |
| /ia/duplicates/ | Duplicate Activity Review Queue - Edify Command Center | ADMIN, IA | pages/ia/duplicate_review.html | 9.4 | 0 | coverage review required |
| /ia/duplicates/<str:duplicate_id>/action | Ia Duplicate Action | ADMIN, IA | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /ia/history/ | Verification History - Edify Command Center | ADMIN, IA | pages/ia/verification_history.html | 9.4 | 0 | referenced by automated test |
| /ia/notifications/ | IA Quality Notifications - Edify Command Center | ADMIN | pages/ia/notifications.html | 9.4 | 0 | coverage review required |
| /ia/returned/ | Returned Activities Ledger - Edify Command Center | ADMIN, IA | pages/ia/returned_activities.html | 9.4 | 0 | coverage review required |
| /ia/verification/ | Verification Queue | ADMIN, IA | pages/ia/partials/queue_table.html<br>pages/ia/verification_queue.html | 9.4 | 0 | referenced by automated test |
| /ia/verification/<str:activity_id>/ | IA Review Workspace - Edify | ADMIN | pages/ia/review_workspace.html | 9.6 | 0 | coverage review required |
| /ia/verification/<str:activity_id>/return | Ia Return Action | ADMIN | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /ia/verification/<str:activity_id>/verify | Ia Verify Action | ADMIN | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /impact | Impact Analytics | ADMIN, CD, IA, PL, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /leave-requests | Leave Requests | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /leave/approvals | Leave Approvals Cockpit | ADMIN, CD, HR, PL, RVP | pages/leave/leave_approvals.html | 9.7 | 0 | referenced by automated test |
| /leave/approvals/ | Leave Approvals Cockpit | ADMIN, CD, HR, PL, RVP | pages/leave/leave_approvals.html | 9.7 | 0 | referenced by automated test |
| /leave/approvals/<str:leave_id>/approve | Leave Approve Action | ADMIN, CD, HR, PL, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /leave/approvals/<str:leave_id>/escalate | Leave Escalate Action | ADMIN, CD, HR, PL, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /leave/approvals/<str:leave_id>/impact | Leave Impact Partial | ADMIN, CD, HR, PL, RVP | partials/leave/impact_panel.html | 9.7 | 0 | coverage review required |
| /leave/approvals/<str:leave_id>/impact/ | Leave Impact Partial | ADMIN, CD, HR, PL, RVP | partials/leave/impact_panel.html | 9.7 | 0 | coverage review required |
| /leave/approvals/<str:leave_id>/reassign | Leave Reassign Coverage Action | ADMIN, CD, HR, PL, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /leave/approvals/<str:leave_id>/reject | Leave Reject Action | ADMIN, CD, HR, PL, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /leave/approvals/<str:leave_id>/return | Leave Return Action | ADMIN, CD, HR, PL, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /leave/calendar | Team Leave Calendar | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/leave/leave_calendar.html | 9.6 | 0 | coverage review required |
| /leave/calendar/ | Team Leave Calendar | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/leave/leave_calendar.html | 9.6 | 0 | coverage review required |
| /leave/coverage | Delegated Coverage Access | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, RVP | pages/leave/leave_coverage.html | 9.7 | 0 | referenced by automated test |
| /leave/coverage/ | Delegated Coverage Access | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, RVP | pages/leave/leave_coverage.html | 9.7 | 0 | referenced by automated test |
| /leave/coverage/<str:assignment_id>/revoke | Revoke Coverage Action | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /leave/coverage/<str:leave_id>/accept | Leave Coverage Accept Action | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /leave/coverage/<str:leave_id>/decline | Leave Coverage Decline Action | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /leave/policies | HR Leave & Policy Settings | ADMIN, HR | pages/leave/leave_policies.html | 9.7 | 0 | coverage review required |
| /leave/policies/ | HR Leave & Policy Settings | ADMIN, HR | pages/leave/leave_policies.html | 9.7 | 0 | coverage review required |
| /leave/team-availability | Team Availability Heatmap | ADMIN, CD, HR, PL, RVP | pages/leave/team_availability.html | 9.6 | 0 | referenced by automated test |
| /leave/team-availability/ | Team Availability Heatmap | ADMIN, CD, HR, PL, RVP | pages/leave/team_availability.html | 9.6 | 0 | referenced by automated test |
| /leave/tracker | Team Leave & Coverage Tracker | ADMIN, CD, HR, PL, RVP | pages/leave/leave_tracker.html | 9.6 | 0 | referenced by automated test |
| /leave/tracker/ | Team Leave & Coverage Tracker | ADMIN, CD, HR, PL, RVP | pages/leave/leave_tracker.html | 9.6 | 0 | referenced by automated test |
| /login | Sign in | Unmapped | pages/auth/login.html | 9.6 | 0 | referenced by automated test |
| /map | School Map · Edify | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | pages/map/index.html | 9.4 | 0 | referenced by automated test |
| /messages | Messages | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/messages/inbox_update.html<br>pages/messages/index.html | 9.7 | 0 | referenced by automated test |
| /messages/ | Messages | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/messages/inbox_update.html<br>pages/messages/index.html | 9.7 | 0 | referenced by automated test |
| /messages/<str:message_id> | Message Detail | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /messages/attachments/<str:attachment_id> | Message Attachment Download | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /messages/new | New Message | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/messages/new.html | 9.8 | 0 | referenced by automated test |
| /messages/new/ | New Message | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/messages/new.html | 9.8 | 0 | referenced by automated test |
| /messages/new/records | Message Compose Records | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/messages/context_records.html | 9.6 | 0 | referenced by automated test |
| /messages/new/suggestions | Message Compose Suggestions | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/messages/recipient_suggestions.html | 9.7 | 0 | referenced by automated test |
| /messages/new/summary | Message Compose Summary | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/messages/context_summary.html | 9.4 | 0 | referenced by automated test |
| /messages/thread/<str:thread_id> | Message Thread | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/messages/conversation.html | 9.6 | 0 | referenced by automated test |
| /messages/thread/<str:thread_id>/archive | Message Thread Archive | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /messages/thread/<str:thread_id>/reply | Message Thread Reply | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/messages/conversation.html | 9.6 | 0 | referenced by automated test |
| /messages/thread/<str:thread_id>/star | Message Thread Star | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /my-plan | My Plan | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/workspace.html<br>pages/my_plan/index.html | 9.4 | 0 | referenced by automated test |
| /my-plan/<str:activity_id> | Activity Details | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/activity_detail_drawer.html<br>pages/my_plan/detail.html | 9.6 | 0 | referenced by automated test |
| /my-plan/<str:activity_id>/accountability | Accountability Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/accountability_drawer.html | 9.6 | 0 | referenced by automated test |
| /my-plan/<str:activity_id>/complete | Complete Activity | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /my-plan/<str:activity_id>/complete-drawer | Complete Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/complete_drawer.html | 9.6 | 0 | referenced by automated test |
| /my-plan/<str:activity_id>/confirm-reimbursement-receipt | Confirm Reimbursement Receipt Action | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/confirm_reimbursement_receipt_drawer.html | 9.6 | 0 | referenced by automated test |
| /my-plan/<str:activity_id>/request-amendment | Request Budget Amendment | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /my-plan/<str:activity_id>/reschedule | Reschedule Activity | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /my-plan/<str:activity_id>/reschedule-drawer | Reschedule Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/my_plan/reschedule_drawer.html | 9.6 | 0 | referenced by automated test |
| /my-professional-development | My Professional Development | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/professional_development/body.html<br>pages/professional_development/index.html | 9.6 | 0 | referenced by automated test |
| /my-professional-development/ | My Professional Development | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/professional_development/body.html<br>pages/professional_development/index.html | 9.6 | 0 | referenced by automated test |
| /my-professional-development/allocation-history | Pd Allocation History | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/professional_development/allocation_history_drawer.html | 9.4 | 0 | coverage review required |
| /my-professional-development/certificate/<str:file_id> | Pd Certificate File | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /my-professional-development/evidence/<str:file_id> | Pd Evidence File | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /my-professional-development/export | Pd Export | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /my-professional-development/fund/<str:fund_request_id>/action | Pd Fund Action | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /my-professional-development/request | Pd Request | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | partials/professional_development/request_form.html | 9.7 | 0 | referenced by automated test |
| /my-professional-development/request/<str:request_id>/action | Pd Action | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /my-professional-development/request/<str:request_id>/certificate | Pd Certificate Upload | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /my-professional-development/request/<str:request_id>/evidence | Pd Evidence Upload | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /my-targets | My Target | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/targets/my_body.html<br>pages/targets/index.html | 9.4 | 0 | referenced by automated test |
| /my-targets/area-drawer | My Targets Area Drawer | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | partials/targets/area_drawer.html | 9.4 | 0 | referenced by automated test |
| /my-targets/export | My Targets Export | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /my-targets/mscs | My Targets Mscs | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /my-team | My Team | ADMIN, CD, HR, PL | pages/my_team/index.html | 9.4 | 0 | referenced by automated test |
| /notifications | Notifications Center | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/notifications/index.html | 9.4 | 0 | referenced by automated test |
| /notifications/ | Notifications Center | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/notifications/index.html | 9.4 | 0 | referenced by automated test |
| /notifications/<str:notif_id>/read | Mark Notif Read | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/notifications/notification_drawer_list.html | 9.4 | 0 | referenced by automated test |
| /notifications/drawer | Notifications Drawer | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/notifications/notification_drawer.html | 9.4 | 0 | referenced by automated test |
| /notifications/mark-all-read | Mark All Notifications Read | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/notifications/notification_drawer_list.html | 9.4 | 0 | referenced by automated test |
| /offboarding | Offboarding | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /onboarding | Onboarding | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /org-structure | Organization Structure | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /partials/clusters/<str:cluster_id>/schools | Cluster Schools Partial | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/clusters/cluster_schools_table.html | 9.4 | 0 | referenced by automated test |
| /partials/costing/preview | Cost Preview | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/cost_preview.html | 9.6 | 0 | referenced by automated test |
| /partner/activities | Activities · Partner Portal · Edify | ADMIN, PARTNER | pages/partner/activities.html | 9.4 | 0 | referenced by automated test |
| /partner/evidence | Evidence · Partner Portal · Edify | ADMIN, PARTNER | pages/partner/evidence.html | 9.4 | 0 | referenced by automated test |
| /partner/my-plan | Partner My Plan | ADMIN, PARTNER | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /partner/schools | Assigned Schools · Partner Portal · Edify | ADMIN, PARTNER | pages/partner/schools.html | 9.4 | 0 | referenced by automated test |
| /partner/today | Today · Partner Portal · Edify | ADMIN, PARTNER | pages/partner/today.html | 9.4 | 0 | referenced by automated test |
| /partners | Partners | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/partners/index.html | 9.4 | 0 | referenced by automated test |
| /partners/<str:partner_id> | Edify | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/partners/detail.html | 9.4 | 0 | coverage review required |
| /payroll-readiness | Payroll Readiness | ACCOUNTANT, ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /performance-reviews | Performance Reviews | ADMIN, CD, HR, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /personal-time-off | Personal Time Off · Edify | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/leave/personal_time_off.html | 9.7 | 0 | referenced by automated test |
| /personal-time-off/ | Personal Time Off · Edify | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/leave/personal_time_off.html | 9.7 | 0 | referenced by automated test |
| /personal-time-off/eligible-cover | Eligible Cover Api | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /personal-time-off/request | Request Leave Drawer | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/leave/request_leave_drawer.html | 9.8 | 0 | referenced by automated test |
| /personal-time-off/request/ | Request Leave Drawer View | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | partials/leave/request_leave_drawer.html | 9.8 | 0 | referenced by automated test |
| /pl/review-queue | PL Review Queue - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/my_plan/pl_queue.html | 9.4 | 0 | referenced by automated test |
| /pl/review-queue/<str:activity_id>/confirm | Pl Confirm | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /pl/review-queue/<str:activity_id>/return | Pl Return | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /planning | Planning | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/planning/school_table.html<br>pages/planning/index.html | 9.6 | 0 | referenced by automated test |
| /planning/assign-partner-action | Planning Assign Partner Action | ADMIN, CCEO, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /planning/assign-partner-modal | Planning Assign Partner Modal | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/planning/assign_partner_drawer.html | 9.7 | 0 | referenced by automated test |
| /planning/bulk-action | Planning Bulk Action | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/planning/reason_required_notice.html | 9.4 | 0 | referenced by automated test |
| /planning/intelligence | Planning Intelligence | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/planning/right_panel.html | 9.4 | 0 | referenced by automated test |
| /planning/route-preview | Planning Route Preview | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/planning/route_preview.html | 9.6 | 0 | referenced by automated test |
| /planning/schedule | Schedule Activity - Edify Command Center | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/planning/schedule.html | 9.4 | 0 | referenced by automated test |
| /planning/schedule-action | Planning Schedule Action | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/planning/reason_required_notice.html | 9.4 | 0 | referenced by automated test |
| /planning/schedule-modal | Planning Schedule Modal | ADMIN, CCEO, PL, PROJECT_COORDINATOR | partials/planning/schedule_cluster_drawer.html<br>partials/planning/schedule_drawer.html | 9.6 | 0 | referenced by automated test |
| /policies | Policies & Documents | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /profile | My Profile | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/profile/index.html | 9.4 | 0 | referenced by automated test |
| /projects | Special Projects | ADMIN, CCEO, CD, PL, PROJECT_COORDINATOR | pages/projects/index.html | 9.6 | 0 | referenced by automated test |
| /projects/<str:project_id> | Edify Command Center | ADMIN, CCEO, CD, PL, PROJECT_COORDINATOR | pages/projects/detail.html | 9.4 | 0 | referenced by automated test |
| /projects/analytics | Analytics | ADMIN, CCEO, CD, PL, PROJECT_COORDINATOR | partials/projects/analytics_workspace.html<br>pages/projects/analytics.html | 9.6 | 0 | referenced by automated test |
| /projects/my-plan | My Plan | ADMIN, CCEO, CD, PL, PROJECT_COORDINATOR | partials/projects/my_plan_workspace.html<br>pages/projects/my_plan.html | 9.7 | 0 | referenced by automated test |
| /projects/planning | Planning | ADMIN, CCEO, CD, PL, PROJECT_COORDINATOR | partials/projects/planning_workspace.html<br>pages/projects/planning.html | 9.8 | 0 | referenced by automated test |
| /projects/planning/bulk-partner | Special Projects Bulk Partner | ADMIN, CCEO, CD, PL, PROJECT_COORDINATOR | partials/projects/bulk_partner_drawer.html | 9.7 | 0 | referenced by automated test |
| /projects/planning/bulk-schedule | Special Projects Bulk Schedule | ADMIN, CCEO, CD, PL, PROJECT_COORDINATOR | partials/projects/bulk_schedule_drawer.html | 9.7 | 0 | referenced by automated test |
| /public-holidays | Calendar Blocks & Public Holidays | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/leave/public_holidays.html | 9.7 | 0 | referenced by automated test |
| /public-holidays/ | Calendar Blocks & Public Holidays | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/leave/public_holidays.html | 9.7 | 0 | referenced by automated test |
| /quality-checks | Quality Checks | ADMIN, CD, IA, PL | pages/quality_checks/index.html | 9.4 | 0 | referenced by automated test |
| /recovery-plans | Recovery Plans | ADMIN, HR, PL | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /recruitment | Recruitment | ADMIN, CD, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /reports | Reports & Performance | ADMIN, CD, IA, PL, PROJECT_COORDINATOR, RVP | pages/reports/index.html | 9.4 | 0 | referenced by automated test |
| /rvp/annual/<str:budget_id>/action | Rvp Annual Action | ADMIN | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /rvp/approvals | Rvp Approvals | ADMIN | partials/dashboards/rvp/approvals_drawer.html | 9.6 | 0 | referenced by automated test |
| /rvp/project/<str:project_id>/decision | Rvp Project Decision | ADMIN | Dynamic / none detected | 9.4 | 0 | coverage review required |
| /rvp/strategy-note | Rvp Strategy Note | ADMIN | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /schools | Schools | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | partials/schools/htmx_response.html<br>pages/schools/index.html | 9.4 | 0 | referenced by automated test |
| /schools/<str:school_id> | School 360 | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | pages/schools/detail.html | 9.4 | 0 | referenced by automated test |
| /schools/<str:school_id>/add-to-cluster | Add To Cluster Drawer | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | partials/schools/drawer_error.html<br>partials/schools/add_to_cluster_drawer.html<br>partials/schools/toast_success.html | 9.7 | 0 | referenced by automated test |
| /schools/<str:school_id>/assign-to-project | Assign To Project Drawer | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | partials/schools/drawer_error.html<br>partials/schools/assign_to_project_drawer.html<br>partials/schools/toast_success.html | 9.6 | 0 | referenced by automated test |
| /schools/<str:school_id>/change-type | School Change Type | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /schools/<str:school_id>/delete | School Delete | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /schools/<str:school_id>/edit-drawer | School Edit Drawer | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | partials/schools/edit_drawer.html | 9.6 | 0 | referenced by automated test |
| /schools/add-school | Add School | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /schools/bulk-assign-cluster | Bulk Assign Cluster | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /schools/bulk-assign-project | Bulk Assign Project | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /schools/bulk-match-staff | Bulk Match Staff | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /schools/create-drawer | School Onboard Drawer | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | partials/schools/onboard_drawer.html | 9.6 | 0 | referenced by automated test |
| /schools/partial-intelligence/<str:school_id> | School Intelligence Partial | ADMIN, CCEO, CD, IA, PL, PROJECT_COORDINATOR | partials/schools/directory_intelligence.html | 9.6 | 0 | referenced by automated test |
| /schools/upload | Upload Data - Edify Command Center | ADMIN, IA | partials/upload_result.html<br>pages/schools/upload.html | 9.7 | 0 | referenced by automated test |
| /schools/upload/<str:batch_id>/preview | School Upload Preview | ADMIN, IA | pages/schools/upload_preview.html | 9.7 | 0 | referenced by automated test |
| /schools/upload/template | School Template Download | ADMIN, IA | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /schools/uploads/<str:batch_id>/result | Import Results | ADMIN, IA | pages/schools/import_result.html | 9.4 | 0 | referenced by automated test |
| /search | Search | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/search/index.html | 9.6 | 0 | referenced by automated test |
| /settings | Settings · Edify | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/settings/index.html | 9.4 | 0 | referenced by automated test |
| /ssa | SSA Performance | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /ssa/export | Ssa Performance Export | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /ssa/unmatched | Unmatched SSA Queue | ADMIN, IA | pages/admin/unmatched_ssa_queue.html | 9.6 | 0 | referenced by automated test |
| /ssa/upload/ | SSA Upload Center | ADMIN, CCEO, CD, IA, PL, RVP | pages/ssa/upload_center.html | 9.6 | 0 | referenced by automated test |
| /ssa/upload/<str:batch_id>/preview/ | SSA Upload Preview | ADMIN, CCEO, CD, IA, PL, RVP | pages/ssa/upload_preview.html | 9.7 | 0 | referenced by automated test |
| /ssa/upload/<str:batch_id>/result/ | SSA Import Result | ADMIN, CCEO, CD, IA, PL, RVP | pages/ssa/upload_result.html | 9.4 | 0 | referenced by automated test |
| /ssa/upload/template | Ssa Template Download | ADMIN, CCEO, CD, IA, PL, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /ssa/verification/ | IA SSA Verification Queue | ADMIN, CCEO, CD, IA, PL, RVP | pages/ssa/verification_queue.html | 9.7 | 0 | referenced by automated test |
| /staff | Human Resource Dashboard - Edify Command Center | ADMIN, CD, HR, PL, RVP | pages/staff/index.html | 9.4 | 0 | referenced by automated test |
| /staff/<str:user_id> | Staff Profile | ADMIN, CD, HR, PL, RVP | pages/staff/detail.html | 9.4 | 0 | referenced by automated test |
| /succession-planning | Succession Planning | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /system-health | System Health & Integrity - Edify | ADMIN | pages/system_health/index.html | 9.7 | 0 | referenced by automated test |
| /team-targets | Team Target Oversight | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | partials/targets/team/workspace.html<br>pages/targets/team.html | 9.7 | 0 | referenced by automated test |
| /team-targets/ | Team Target Oversight | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | partials/targets/team/workspace.html<br>pages/targets/team.html | 9.7 | 0 | referenced by automated test |
| /team-targets/catchup | Team Targets Catchup Create | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /team-targets/catchup/<str:plan_id>/action | Team Targets Catchup Action | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /team-targets/day | Team Targets Day | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | partials/targets/team/day_drawer.html | 9.4 | 0 | referenced by automated test |
| /team-targets/export | Team Targets Export | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /team-targets/matrix | Team Targets Matrix | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | partials/targets/team/matrix_drawer.html | 9.4 | 0 | referenced by automated test |
| /team-targets/recovery | Team Targets Recovery | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | partials/targets/team/recovery_drawer.html | 9.4 | 0 | referenced by automated test |
| /team-targets/sfid-backlog | Team Targets Sfid Backlog | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | partials/targets/team/sfid_drawer.html | 9.4 | 0 | referenced by automated test |
| /team-targets/staff-drawer | Team Targets Staff Drawer | ACCOUNTANT, ADMIN, CD, HR, IA, PL, PROJECT_COORDINATOR | partials/targets/team/staff_drawer.html | 9.4 | 0 | referenced by automated test |
| /today | Today | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/today/index.html | 9.4 | 0 | referenced by automated test |
| /todos | To-Do | ACCOUNTANT, ADMIN, CCEO, CD, HR, IA, PARTNER, PL, PROJECT_COORDINATOR, RVP | pages/todos/index.html | 9.4 | 0 | referenced by automated test |
| /trainings | Trainings Log | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | pages/trainings/index.html | 9.4 | 0 | referenced by automated test |
| /visits | Visits Log | ADMIN, CCEO, PARTNER, PL, PROJECT_COORDINATOR | pages/visits/index.html | 9.4 | 0 | referenced by automated test |
| /wellness | Wellness | ADMIN, HR | Dynamic / none detected | 9.4 | 0 | referenced by automated test |
| /work-plan | Work Plan | ADMIN, CCEO, PL, PROJECT_COORDINATOR | pages/work_plan/index.html | 9.6 | 0 | referenced by automated test |
| /workforce-planning | Workforce Planning | ADMIN, CD, HR, RVP | Dynamic / none detected | 9.4 | 0 | referenced by automated test |

## Machine-readable source

The complete per-surface workflow, component, state and finding records are in `docs/platform-page-inventory.json`.
