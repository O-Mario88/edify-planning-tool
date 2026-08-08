# Edify mobile UI/UX page-by-page matrix

**Date:** 8 August 2026

**Coverage:** all 145 distinct full-page templates in the authoritative page inventory
**Companion report:** [Mobile UI/UX reference audit](MOBILE_UI_UX_REFERENCE_AUDIT_2026-08-08.md)

This matrix is the implementation-level companion to the main audit. Reused partials and drawers inherit the parent page pattern; the matrix therefore covers full navigable page templates without double-counting HTMX fragments.

**Implementation status:** the shared mobile foundation, all five migration phases, and the exhaustive micro-UX pass are complete. Every role has a task-first home, and the high-frequency templates in each archetype have explicit mobile-family opt-ins. All authenticated routes now also inherit shell-level 44 px control/link targets, 16 px form fields, adaptive semantic tables, keyboard tabs, named pagination, centralized async feedback, and named focus-managed dialogs. The remaining low-frequency rows inherit these contracts; their row-level proposal remains the acceptance guide for future scenario testing and refinements.

**Priority:** P0 = role home/high-frequency bottleneck; P1 = core operational workflow; P2 = important analysis/import/communication; P3 = lower-frequency administration/knowledge.

## Accounts

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Accountability**<br>`pages/accounts/accountability.html` | `/accounts/accountability`<br>`/accounts/accountability/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Activity Evidence**<br>`pages/accounts/activity_evidence.html` | `/accounts/activity-evidence/<str:activity_id>` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Activity Finance Detail**<br>`pages/accounts/activity_finance_detail.html` | `/accounts/activities/<str:activity_id>`<br>`/accounts/activities/<str:activity_id>/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Approval History**<br>`pages/accounts/approval_history.html` | `/accounts/approval-history`<br>`/accounts/approval-history/` | Accountant, Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Audit Log**<br>`pages/accounts/audit_log.html` | `/accounts/audit-log`<br>`/accounts/audit-log/` | Accountant, Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Batch Payments**<br>`pages/accounts/batch_payments.html` | `/accounts/batch-payments`<br>`/accounts/batch-payments/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Blocked**<br>`pages/accounts/blocked.html` | `/accounts/blocked`<br>`/accounts/blocked/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Budget Amendments**<br>`pages/accounts/budget_amendments.html` | `/accounts/budget-amendments` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Cleared**<br>`pages/accounts/cleared.html` | `/accounts/cleared`<br>`/accounts/cleared/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Dashboard**<br>`pages/accounts/dashboard.html` | `/accounts`<br>`/accounts/` | Accountant, Admin | F — Finance decision | Put the oldest ready-to-disburse/reconcile item first; collapse zero metrics and move rules/status charts below the queue. | P0 |
| **Partner Payments**<br>`pages/accounts/partner_payments.html` | `/accounts/partner-payments`<br>`/accounts/partner-payments/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Ready For Advance**<br>`pages/accounts/ready_for_advance.html` | `/accounts/advances`<br>`/accounts/advances/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Returned**<br>`pages/accounts/returned.html` | `/accounts/returned`<br>`/accounts/returned/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Variance Review**<br>`pages/accounts/variance_review.html` | `/accounts/variance-review`<br>`/accounts/variance-review/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Weekly Requests**<br>`pages/accounts/weekly_requests.html` | `/accounts/weekly-requests`<br>`/accounts/weekly-requests/` | Accountant, Admin | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |

## Admin

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Audit Log**<br>`pages/admin/audit_log.html` | `/admin-panel/audit-log` | Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Data Quality Center**<br>`pages/admin/data_quality_center.html` | `/admin-panel/data-quality-center` | Admin, IA | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Duplicate Review**<br>`pages/admin/duplicate_review.html` | `/data-quality/duplicates` | Admin, IA | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Admin**<br>`pages/admin/index.html` | `/admin-panel` | Admin | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Notifications Mgmt**<br>`pages/admin/notifications_mgmt.html` | `/admin-panel/notifications-mgmt` | Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Page Access Matrix**<br>`pages/admin/page_access_matrix.html` | `/admin-panel/page-access-matrix` | Admin | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Region District Setup**<br>`pages/admin/region_district_setup.html` | `/admin-panel/region-district-setup` | Admin | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Roles Permissions**<br>`pages/admin/roles_permissions.html` | `/admin-panel/roles-permissions` | Admin | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **School Upload History**<br>`pages/admin/school_upload_history.html` | `/admin-panel/school-upload-history` | Admin, IA | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Staff Setup Queue**<br>`pages/admin/staff_setup_queue.html` | `/admin-panel/staff-setup-queue` | Admin, CD, HR | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Unmatched Ssa Queue**<br>`pages/admin/unmatched_ssa_queue.html` | `/ssa/unmatched` | Admin, IA | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **User Detail**<br>`pages/admin/user_detail.html` | `/admin-panel/users/<str:user_id>` | Admin, CD, HR | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Users**<br>`pages/admin/users.html` | `/admin-panel/users` | Admin, CD, HR | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Workflow Rules**<br>`pages/admin/workflow_rules.html` | `/admin-panel/workflow-rules` | Admin | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |

## Admin Ops

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Data Repair**<br>`pages/admin_ops/data_repair.html` | `/data-repair` | Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Incident Detail**<br>`pages/admin_ops/incident_detail.html` | `/admin-ops/incidents/<str:incident_id>` | Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Incidents**<br>`pages/admin_ops/incidents.html` | `/admin-ops/incidents` | Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Maintenance**<br>`pages/admin_ops/maintenance.html` | `/admin-ops/maintenance` | Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **My Plan**<br>`pages/admin_ops/my_plan.html` | `/admin-ops/my-plan` | Admin | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Planning**<br>`pages/admin_ops/planning.html` | `/admin-ops/planning` | Admin | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Report Problem**<br>`pages/admin_ops/report_problem.html` | `/support` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Support Queue**<br>`pages/admin_ops/support_queue.html` | `/admin-ops/support` | Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Team Plans**<br>`pages/admin_ops/team_plans.html` | `/admin-ops/team-plans` | Admin | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |

## Analytics

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Declining Schools**<br>`pages/analytics/declining_schools.html` | `/declining-schools` | Admin, CCEO, CD, IA, PL, Project Coordinator, RVP | A — Analytics/insight | Lead with the decision or change, then one trend and a 2 × 2 metric grid; keep tables and broad breakdowns as drill-downs. | P2 |
| **Publishing Status**<br>`pages/analytics/publishing_status.html` | `/analytics/publishing`<br>`/analytics/publishing/` | Admin, CD, IA | A — Analytics/insight | Lead with the decision or change, then one trend and a 2 × 2 metric grid; keep tables and broad breakdowns as drill-downs. | P2 |

## Audit

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Decision Log**<br>`pages/audit/decision_log.html` | `/decision-log` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |

## Auth

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Change Password**<br>`pages/auth/change_password.html` | `/change-password` | Public / signed-in context | K — Knowledge/document | Show password requirements as live checks and retain one sticky-safe submit action. | P3 |
| **Login**<br>`pages/auth/login.html` | `/`<br>`/login` | Public / signed-in context | K — Knowledge/document | Use restrained Edify mission imagery, one clear sign-in form, inline errors, and a low-bandwidth fallback. | P3 |
| **Reset Password**<br>`pages/auth/reset_password.html` | `/reset-password` | Public / signed-in context | K — Knowledge/document | Use one-step recovery with clear delivery confirmation and privacy-safe account messaging. | P3 |

## Budget

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Budget**<br>`pages/budget/index.html` | `/budgets/overview` | Accountant, Admin, CD, IA, RVP | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |

## Budgets

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Monthly**<br>`pages/budgets/monthly.html` | `/country-budget`<br>`/country-budget/` | Accountant, Admin, CD, IA, RVP | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |

## Calendar

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Calendar**<br>`pages/calendar/index.html` | `/calendar` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | C — Calendar/agenda | Default to week strip plus selected-day agenda; place month grid and advanced filters behind controls. | P1 |

## Closure

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Activity Closure Detail**<br>`pages/closure/activity_closure_detail.html` | `/activities/<str:activity_id>/closure`<br>`/activities/<str:activity_id>/closure/` | Admin, CCEO, PL, Project Coordinator | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Activity Timeline**<br>`pages/closure/activity_timeline.html` | `/activities/<str:activity_id>/timeline` | Admin, CCEO, PL, Project Coordinator | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Blocked Closure**<br>`pages/closure/blocked_closure.html` | `/activities/closure/blocked`<br>`/activities/closure/blocked/` | Admin, CCEO, PL, Project Coordinator | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Completed Activities**<br>`pages/closure/completed_activities.html` | `/completed-activities` | Admin, CCEO, IA, PL, Project Coordinator | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Completed Detail**<br>`pages/closure/completed_detail.html` | `/completed-activities/<str:activity_id>`<br>`/completed-activities/<str:activity_id>/` | Admin, CCEO, PL, Project Coordinator | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Readiness Queue**<br>`pages/closure/readiness_queue.html` | `/activities/closure`<br>`/activities/closure/` | Admin, CCEO, PL, Project Coordinator | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |

## Clusters

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Detail**<br>`pages/clusters/detail.html` | `/clusters/<str:cluster_id>` | Admin, CCEO, CD, IA, PL, Partner Admin / Field Officer | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |

## Core Schools

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Champion Candidates**<br>`pages/core_schools/champion_candidates.html` | `/core-schools/champion-candidates` | Admin, CCEO, IA, PL | D — Directory | Use search-first results, three or fewer chips, a filter sheet, compact record cards, and a clear route to record detail. | P1 |
| **Champions**<br>`pages/core_schools/champions.html` | `/core-schools/champions` | Admin, CCEO, IA, PL | D — Directory | Use search-first results, three or fewer chips, a filter sheet, compact record cards, and a clear route to record detail. | P1 |
| **Detail**<br>`pages/core_schools/detail.html` | `/core-schools/<str:plan_id>` | Admin, CCEO, PL, Project Coordinator | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Leadership**<br>`pages/core_schools/leadership.html` | `/core-school-health` | Admin, CD, IA, PL, RVP | A — Analytics/insight | Lead with the decision or change, then one trend and a 2 × 2 metric grid; keep tables and broad breakdowns as drill-downs. | P2 |

## Cost Settings

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Cost Settings**<br>`pages/cost_settings/index.html` | `/cost-settings` | Admin, CD | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |

## Coverage

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Coverage**<br>`pages/coverage/index.html` | `/coverage` | Admin, CD, HR, PL, Project Coordinator, RVP | A — Analytics/insight | Lead with the decision or change, then one trend and a 2 × 2 metric grid; keep tables and broad breakdowns as drill-downs. | P2 |

## Debriefs

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Detail**<br>`pages/debriefs/detail.html` | `/debriefs/<str:debrief_id>` | Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Weekly Report**<br>`pages/debriefs/weekly_report.html` | `/debriefs/weekly-report` | Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |

## Decisions

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Decisions**<br>`pages/decisions/index.html` | `/decisions` | Accountant, Admin, CD, HR, PL, RVP | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |

## Districts

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Detail**<br>`pages/districts/detail.html` | `/districts/<str:district_id>` | Admin, CCEO, PL, Project Coordinator | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Districts**<br>`pages/districts/index.html` | `/districts` | Admin, CCEO, PL, Project Coordinator | D — Directory | Use search-first results, three or fewer chips, a filter sheet, compact record cards, and a clear route to record detail. | P1 |

## Documents

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Agreement Center**<br>`pages/documents/agreement_center.html` | `/policy-agreement` | Public / signed-in context | K — Knowledge/document | Show required agreements, reading time, status, and a single resume/acknowledge action; separate optional documents. | P3 |
| **Canonical Document**<br>`pages/documents/canonical_document.html` | `/documents/<slug:slug>/` | Public / signed-in context | K — Knowledge/document | Use focused reading mode with a contents sheet, progress, downloadable source, and sticky acknowledgement when required. | P3 |
| **Compliance**<br>`pages/documents/compliance.html` | `/policy-compliance` | Admin, CD, HR, PL, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Manage Document**<br>`pages/documents/manage_document.html` | `/documents/<slug:slug>/manage` | Admin, CD, HR, IA, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **New Document**<br>`pages/documents/new_document.html` | `/uploads/new` | Admin, CD, HR, IA, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Restricted**<br>`pages/documents/restricted.html` | `/policy-agreement/restricted` | Public / signed-in context | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Viewer**<br>`pages/documents/viewer.html` | `/documents/<slug:slug>/` | Public / signed-in context | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |

## Escalations

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Escalations**<br>`pages/escalations/index.html` | `/escalations` | Admin, CD, RVP | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |

## Evidence

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Returned**<br>`pages/evidence/returned.html` | `/evidence/returned` | Admin, CCEO, CD, IA, PL, Partner Admin / Field Officer, Project Coordinator | V — Verification/evidence | Show evidence/canonical context first, mismatch/checklist second, and a sticky Verify/Return action with explicit audit consequence. | P1 |

## Finance

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Country Budget History**<br>`pages/finance/country_budget_history.html` | `/country-budget/history` | Accountant, Admin, CD, IA, RVP | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Country Budget Submission**<br>`pages/finance/country_budget_submission.html` | `/country-budget/history/<str:budget_id>` | Accountant, Admin, CD, IA, RVP | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |
| **Fund Allocation**<br>`pages/finance/fund_allocation.html` | `/finance/fund-allocation`<br>`/finance/fund-allocation/` | Accountant, Admin, CD, IA, RVP | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |

## Fund Requests

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Detail**<br>`pages/fund_requests/detail.html` | `/fund-requests/weekly/<str:request_id>` | Accountant, Admin, CCEO, CD, IA, PL, Project Coordinator | F — Finance decision | Lead with amount, stage, age, and responsible person; show the decision queue before rules/history and pin valid review actions. | P1 |

## Fy

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Fy**<br>`pages/fy/index.html` | `/fy` | Admin, CCEO, PL, Project Coordinator | A — Analytics/insight | Lead with the decision or change, then one trend and a 2 × 2 metric grid; keep tables and broad breakdowns as drill-downs. | P2 |

## Help

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Article**<br>`pages/help/article.html` | `/help/articles/<slug:slug>`<br>`/help/context`<br>`/help/getting-started` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Category**<br>`pages/help/category.html` | `/help/categories/<slug:slug>`<br>`/help/troubleshooting` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Edit Article**<br>`pages/help/edit_article.html` | `/help/manage/<slug:slug>`<br>`/help/manage/new` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Glossary**<br>`pages/help/glossary.html` | `/help/glossary` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Help**<br>`pages/help/index.html` | `/help` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Manage**<br>`pages/help/manage.html` | `/help/manage` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Release Notes**<br>`pages/help/release_notes.html` | `/help/release-notes` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |
| **Search**<br>`pages/help/search.html` | `/help/search` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | K — Knowledge/document | Use a search-first hub or focused reader, move contents to a sheet, and keep acknowledgement/edit controls role-appropriate. | P3 |

## Hr

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Conversation Document**<br>`pages/hr/conversation_document.html` | `/performance-conversation/<str:review_id>/document/<str:window>` | Accountant, Admin, CCEO, CD, HR, IA, PL, Project Coordinator, RVP | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **My Performance**<br>`pages/hr/my_performance.html` | `/my-performance`<br>`/my-performance/development`<br>`/my-performance/documents`<br>+1 more | Accountant, Admin, CCEO, CD, HR, IA, PL, Project Coordinator, RVP | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Performance Console**<br>`pages/hr/performance_console.html` | `/hr/performance-cycle` | Admin, HR | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Performance Conversation**<br>`pages/hr/performance_conversation.html` | `/performance-conversation` | Accountant, Admin, CCEO, CD, HR, IA, PL, Project Coordinator, RVP | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Priority Configuration**<br>`pages/hr/priority_configuration.html` | `/strategic-priorities` | Admin, CD, HR, RVP | A — Analytics/insight | Lead with the decision or change, then one trend and a 2 × 2 metric grid; keep tables and broad breakdowns as drill-downs. | P2 |

## Ia

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Activity Timeline**<br>`pages/ia/activity_timeline.html` | `/activities/<str:activity_id>/timeline/` | Admin | V — Verification/evidence | Show evidence/canonical context first, mismatch/checklist second, and a sticky Verify/Return action with explicit audit consequence. | P1 |
| **Analytics Dashboard**<br>`pages/ia/analytics_dashboard.html` | `/ia/dashboard/` | Admin, IA | A — Analytics/insight | Put the oldest SLA-risk verification first; retain four compact exception metrics and move national performance to IA Analytics. | P0 |
| **Compare Evidence**<br>`pages/ia/compare_evidence.html` | `/ia/compare/` | Admin, IA | V — Verification/evidence | Use a synchronized evidence/canonical comparison with highlighted mismatches and a single sticky decision bar. | P1 |
| **Duplicate Review**<br>`pages/ia/duplicate_review.html` | `/ia/duplicates/` | Admin, IA | V — Verification/evidence | Show evidence/canonical context first, mismatch/checklist second, and a sticky Verify/Return action with explicit audit consequence. | P1 |
| **Notifications**<br>`pages/ia/notifications.html` | `/ia/notifications/` | Admin | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Returned Activities**<br>`pages/ia/returned_activities.html` | `/ia/returned/` | Admin, IA | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Review Workspace**<br>`pages/ia/review_workspace.html` | `/ia/verification/<str:activity_id>/` | Admin | V — Verification/evidence | Keep evidence and canonical record visible, show mismatch/checklist next, and pin Verify/Return above bottom navigation. | P1 |
| **Verification History**<br>`pages/ia/verification_history.html` | `/ia/history/` | Admin, IA | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |

## Leave

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Leave Approvals**<br>`pages/leave/leave_approvals.html` | `/leave/approvals`<br>`/leave/approvals/` | Admin, CD, HR, PL, RVP | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Leave Calendar**<br>`pages/leave/leave_calendar.html` | `/leave/calendar`<br>`/leave/calendar/` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | C — Calendar/agenda | Use a week/day agenda by default, compact availability signals, and move month-wide or advanced controls into drill-downs. | P1 |
| **Leave Coverage**<br>`pages/leave/leave_coverage.html` | `/leave/coverage`<br>`/leave/coverage/` | Accountant, Admin, CCEO, CD, HR, IA, PL, RVP | C — Calendar/agenda | Use a week/day agenda by default, compact availability signals, and move month-wide or advanced controls into drill-downs. | P1 |
| **Leave Policies**<br>`pages/leave/leave_policies.html` | `/leave/policies`<br>`/leave/policies/` | Admin, HR | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Leave Tracker**<br>`pages/leave/leave_tracker.html` | `/leave/tracker`<br>`/leave/tracker/` | Admin, CD, HR, PL, RVP | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |
| **Personal Time Off**<br>`pages/leave/personal_time_off.html` | `/personal-time-off`<br>`/personal-time-off/` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | Q — Work queue | Lead with balance and the next leave action; show upcoming requests as cards and move history/table detail below. | P1 |
| **Public Holidays**<br>`pages/leave/public_holidays.html` | `/public-holidays`<br>`/public-holidays/` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | C — Calendar/agenda | Use a week/day agenda by default, compact availability signals, and move month-wide or advanced controls into drill-downs. | P1 |
| **Team Availability**<br>`pages/leave/team_availability.html` | `/leave/team-availability`<br>`/leave/team-availability/` | Admin, CD, HR, PL, RVP | C — Calendar/agenda | Use a week/day agenda by default, compact availability signals, and move month-wide or advanced controls into drill-downs. | P1 |

## Map

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Map**<br>`pages/map/index.html` | `/map` | Admin, CCEO, CD, IA, PL, Project Coordinator | D — Directory | Use search-first results, three or fewer chips, a filter sheet, compact record cards, and a clear route to record detail. | P1 |

## Messages

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **New**<br>`pages/messages/new.html` | `/messages/new`<br>`/messages/new/` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | M — Messaging | Use a simple recipient/topic/message sequence with attachment status, autosaved draft, and clear send confirmation. | P2 |

## My Plan

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Evidence Packet**<br>`pages/my_plan/evidence_packet.html` | `/activities/<str:activity_id>/evidence/detail` | Admin, CCEO, PL, Partner Admin / Field Officer, Project Coordinator | P — Planner/workflow | Lead with the next workflow step and current period; use a compact stepper/agenda and a sticky create, schedule, or submit action. | P1 |
| **Pl Queue**<br>`pages/my_plan/pl_queue.html` | `/pl/review-queue` | Admin, CCEO, PL, Project Coordinator | P — Planner/workflow | Lead with the next workflow step and current period; use a compact stepper/agenda and a sticky create, schedule, or submit action. | P1 |

## My Team

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **My Team**<br>`pages/my_team/index.html` | `/my-team` | Admin, CD, HR, PL | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |

## Notifications

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Notifications**<br>`pages/notifications/index.html` | `/notifications`<br>`/notifications/` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | Q — Work queue | Put prioritized records before summary analytics; use search/status segments, compact cards, and reveal batch actions only after selection. | P1 |

## Partner

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Activities**<br>`pages/partner/activities.html` | `/partner/activities` | Admin, Partner Admin / Field Officer | P — Planner/workflow | Lead with the next workflow step and current period; use a compact stepper/agenda and a sticky create, schedule, or submit action. | P1 |
| **Evidence**<br>`pages/partner/evidence.html` | `/partner/evidence` | Admin, Partner Admin / Field Officer | V — Verification/evidence | Show evidence/canonical context first, mismatch/checklist second, and a sticky Verify/Return action with explicit audit consequence. | P1 |
| **Schools**<br>`pages/partner/schools.html` | `/partner/schools` | Admin, Partner Admin / Field Officer | D — Directory | Use search-first results, three or fewer chips, a filter sheet, compact record cards, and a clear route to record detail. | P1 |
| **Today**<br>`pages/partner/today.html` | `/partner/today` | Admin, Partner Admin / Field Officer | H — Role home | Keep this task-first structure; add a day strip, Start/Continue state, route/location context, sync state, and evidence handoff. | P0 |

## Partners

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Detail**<br>`pages/partners/detail.html` | `/partners/<str:partner_id>` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Partners**<br>`pages/partners/index.html` | `/partners` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | D — Directory | Use search-first results, three or fewer chips, a filter sheet, compact record cards, and a clear route to record detail. | P1 |

## Planning

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Schedule**<br>`pages/planning/schedule.html` | `/planning/schedule` | Admin, CCEO, PL, Project Coordinator | P — Planner/workflow | Lead with the next workflow step and current period; use a compact stepper/agenda and a sticky create, schedule, or submit action. | P1 |

## Profile

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Profile**<br>`pages/profile/index.html` | `/profile` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | R — Record detail | Lead with identity, role, territory, and current availability; group security/preferences and make editable fields explicit. | P3 |

## Projects

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Detail**<br>`pages/projects/detail.html` | `/projects/<str:project_id>` | Admin, CCEO, CD, IA, PL, Project Coordinator | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |

## Quality Checks

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Quality Checks**<br>`pages/quality_checks/index.html` | `/quality-checks` | Admin, CD, IA, PL | V — Verification/evidence | Show evidence/canonical context first, mismatch/checklist second, and a sticky Verify/Return action with explicit audit consequence. | P1 |

## Reports

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Reports**<br>`pages/reports/index.html` | `/reports` | Admin, CD, IA, PL, Project Coordinator, RVP | A — Analytics/insight | Lead with the decision or change, then one trend and a 2 × 2 metric grid; keep tables and broad breakdowns as drill-downs. | P2 |

## Schools

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Closed**<br>`pages/schools/closed.html` | `/schools/closed` | Admin, CCEO, CD, IA, PL | D — Directory | Use search-first results, three or fewer chips, a filter sheet, compact record cards, and a clear route to record detail. | P1 |
| **Detail**<br>`pages/schools/detail.html` | `/schools/<str:school_id>` | Admin, CCEO, CD, IA, PL, Project Coordinator | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Import Result**<br>`pages/schools/import_result.html` | `/schools/uploads/<str:batch_id>/result` | Admin, IA | U — Upload/import | Use an explicit Upload → Validate → Review → Commit flow with resumable progress, errors first, and a safe final summary. | P2 |
| **Upload Preview**<br>`pages/schools/upload_preview.html` | `/schools/upload/<str:batch_id>/preview` | Admin, IA | U — Upload/import | Use an explicit Upload → Validate → Review → Commit flow with resumable progress, errors first, and a safe final summary. | P2 |

## Search

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Search**<br>`pages/search/index.html` | `/search` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | D — Directory | Show contextual recent/suggested results, one search field, type chips, and grouped record cards with highlighted matches. | P1 |

## Settings

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Activity Catalogue**<br>`pages/settings/activity_catalogue.html` | `/settings/activity-catalogue/` | Public / signed-in context | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |
| **Settings**<br>`pages/settings/index.html` | `/settings` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | S — Settings/admin | Use searchable grouped settings with current status/effect; isolate access-changing or destructive actions behind confirmation. | P3 |

## Ssa

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Manual Entry**<br>`pages/ssa/manual_entry.html` | `/ssa/manual/` | Admin, CCEO, CD, IA, PL, RVP | U — Upload/import | Use an explicit Upload → Validate → Review → Commit flow with resumable progress, errors first, and a safe final summary. | P2 |
| **Upload Center**<br>`pages/ssa/upload_center.html` | `/ssa/upload/` | Admin, CCEO, CD, IA, PL, RVP | U — Upload/import | Use Upload → Validate → Review → Commit, resumable progress, and an error-first review summary. | P2 |
| **Upload Preview**<br>`pages/ssa/upload_preview.html` | `/ssa/upload/<str:batch_id>/preview/` | Admin, CCEO, CD, IA, PL, RVP | U — Upload/import | Use an explicit Upload → Validate → Review → Commit flow with resumable progress, errors first, and a safe final summary. | P2 |
| **Upload Result**<br>`pages/ssa/upload_result.html` | `/ssa/upload/<str:batch_id>/result/` | Admin, CCEO, CD, IA, PL, RVP | U — Upload/import | Use an explicit Upload → Validate → Review → Commit flow with resumable progress, errors first, and a safe final summary. | P2 |
| **Verification Queue**<br>`pages/ssa/verification_queue.html` | `/ssa/verification/` | Admin, CCEO, CD, IA, PL, RVP | V — Verification/evidence | Show evidence/canonical context first, mismatch/checklist second, and a sticky Verify/Return action with explicit audit consequence. | P1 |

## Staff

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Detail**<br>`pages/staff/detail.html` | `/staff/<str:user_id>` | Admin, CD, HR, PL, RVP | R — Record detail | Lead with identity/status and key facts, pin the next valid action, and organize history/evidence/finance into tabs or accordions. | P3 |
| **Staff**<br>`pages/staff/index.html` | `/staff` | Admin, CD, HR, PL, RVP | D — Directory | Use a search-first people directory and compact 2 × 2 workforce summary; move filters to a sheet and tables to record cards. | P1 |

## System Health

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **System Health**<br>`pages/system_health/index.html` | `/system-health` | Admin | A — Analytics/insight | Lead with overall service health and active incident; show four compact signals, then trends and component drill-downs. | P2 |

## Today

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Today**<br>`pages/today/index.html` | `/today` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | P — Planner/workflow | Lead with the next workflow step and current period; use a compact stepper/agenda and a sticky create, schedule, or submit action. | P1 |

## Todos

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Todos**<br>`pages/todos/index.html` | `/todos` | Accountant, Admin, CCEO, CD, HR, IA, PL, Partner Admin / Field Officer, Project Coordinator, RVP | P — Planner/workflow | Replace six full-width summaries with a compact 2 × 2 strip and begin the prioritized task list in the first viewport. | P0 |

## Trainings

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Trainings**<br>`pages/trainings/index.html` | `/trainings` | Admin, CCEO, PL, Partner Admin / Field Officer, Project Coordinator | P — Planner/workflow | Lead with the next workflow step and current period; use a compact stepper/agenda and a sticky create, schedule, or submit action. | P1 |

## Visits

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Visits**<br>`pages/visits/index.html` | `/visits` | Admin, CCEO, PL, Partner Admin / Field Officer, Project Coordinator | P — Planner/workflow | Lead with the next workflow step and current period; use a compact stepper/agenda and a sticky create, schedule, or submit action. | P1 |

## Work Plan

| Page | Route(s) | Roles | Target pattern | Mobile proposal | Priority |
|---|---|---|---|---|---|
| **Work Plan**<br>`pages/work_plan/index.html` | `/work-plan`<br>`/work-plan/` | Accountant, Admin, CCEO, CD, HR, IA, PL, Project Coordinator, RVP | P — Planner/workflow | Show current-period work and the next submission action before approval history/export; use period cards and a compact stepper. | P1 |

## Coverage check

- Full-page templates represented: **145 of 145**
- Routed full-page surface entries consolidated: **325**
- Role labels reflect inventory access groups; object-level permissions and data scope remain enforced by the existing backend.
