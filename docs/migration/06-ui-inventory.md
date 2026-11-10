# 6. Frontend inventory

Generated on 2026-11-10 from `main` at `deefe6f6f`: the templates on disk and the
navigation the application's own code builds for each seeded role. This is the
full list of what a native rebuild has to cover.

## 6.1 Size

| What | Count |
|---|---|
| Full-page templates | 248 in 68 areas |
| Partial templates (drawers, tables, cards, rows) | 637 |
| Shared components (`templates/components`) | 32 |
| Page and action routes (`apps/frontend/urls.py`) | 906 |
| Stylesheets | 18 files, 1.6 MB |
| Distinct navigation destinations across all roles | 140 |
| Roles | 15 |

## 6.2 Navigation per role

The bottom navigation is not the same for everyone: each role gets Home, two
role-specific destinations, Messages and More.

| Role | Sidebar destinations | Bottom navigation |
|---|---|---|
| Accountant | 19 | Home · Funds · Payments · Messages · More |
| Admin | 115 | Home · Support · Health · Messages · More |
| BusinessTransformationOfficer | 10 | Home · BT Overview · To-Do · Messages · More |
| CCEO | 31 | Home · My Plan · Schools · Messages · More |
| CountryDirector | 52 | Home · Budget · Reports · Messages · More |
| HumanResources | 38 | Home · People · Leave · Messages · More |
| ImpactAssessment | 39 | Home · To-Do · Verify · Messages · More |
| MfiLoanOfficer | 10 | Home · Dashboard · To-Do · Messages · More |
| MfiPartnerAdmin | 10 | Home · Dashboard · To-Do · Messages · More |
| PartnerAdmin | 12 | Home · My Plan · Schools · Messages · More |
| PartnerFieldOfficer | 12 | Home · My Plan · Schools · Messages · More |
| Program Lead | 38 | Home · My Plan · Oversight · Messages · More |
| ProjectCoordinator | 16 | Home · Projects · My Plan · Messages · More |
| RegionalProgramLead | 18 | Home · To-Do · Messages · Dashboard · More |
| RegionalVicePresident | 34 | Home · Budget · Reports · Messages · More |

## 6.3 Every navigation destination

`Native` says what the React Native app shows today. Everything else is still
only on the web app.

| Destination | Path | Roles that see it | Native |
|---|---|---|---|
| Decision Log | `/decision-log` | 15 | — |
| Calendar | `/calendar` | 14 | — |
| To-Do | `/todos` | 14 | — |
| Leave & Personal Time Off | `/personal-time-off/` | 13 | — |
| My Actions | `/actions/mine` | 13 | — |
| School Directory | `/schools` | 10 | **Exact (read)**: header, filters, views, rows, details, paging. Actions, Add School, Export and bulk selection open on the web |
| Field Debrief | `/debriefs` | 9 | — |
| Cluster Oversight | `/cluster-oversight/` | 8 | — |
| Dashboard | `/dashboard` | 8 | — |
| My Performance Agreement | `/my-performance` | 8 | — |
| My Professional Development | `/my-professional-development` | 8 | — |
| Partner Oversight | `/partner-oversight/` | 8 | — |
| Core School Oversight | `/core-schools-oversight/` | 7 | — |
| Team Performance | `/team-performance/` | 7 | — |
| Budget | `/budget` | 6 | — |
| Escalations | `/escalations` | 6 | — |
| My Targets | `/my-targets` | 6 | — |
| Planning | `/planning` | 6 | — |
| Planning Oversight | `/team-planning-oversight/` | 6 | — |
| Project Monitoring | `/projects/monitoring` | 6 | — |
| Work Plan | `/work-plan` | 6 | — |
| Closed Schools | `/schools/closed` | 5 | — |
| Country Map | `/country-map/` | 5 | — |
| Loans | `/loans` | 5 | — |
| My Plan | `/my-plan` | 5 | — |
| Programme Schools | `/programme-schools` | 5 | — |
| Reports | `/reports` | 5 | — |
| Upload Center | `/uploads` | 5 | — |
| Weekly Advance Request | `/fund-requests/weekly` | 5 | — |
| Acting Leadership | `/acting-leadership` | 4 | — |
| Actions Sent | `/actions/sent` | 4 | — |
| CPD & Learning | `/cpd-learning` | 4 | — |
| Clusters | `/clusters` | 4 | — |
| Country Oversight | `/country-planning-oversight/` | 4 | — |
| HR Today | `/hr-today` | 4 | — |
| Impact Reports | `/ia/impact-reports/` | 4 | — |
| Leave Approvals | `/leave/approvals` | 4 | — |
| People Directory | `/staff` | 4 | — |
| Performance Reviews | `/performance-reviews` | 4 | — |
| Policy Compliance | `/policy-compliance` | 4 | — |
| Workforce Planning | `/workforce-planning` | 4 | — |
| Assigned Activities | `/partner/assigned-activities` | 3 | — |
| Assigned Schools | `/partner/assigned-schools` | 3 | — |
| CCE Reports | `/cce-leadership/reports` | 3 | — |
| Completed & Payments | `/partner/completed` | 3 | — |
| Core Schools | `/core-schools` | 3 | — |
| Cost Intelligence | `/cost-intelligence` | 3 | — |
| Evidence | `/partner/evidence` | 3 | — |
| Extra Work | `/extra-work` | 3 | — |
| Fund Approvals | `/fund-approvals` | 3 | — |
| Priorities | `/target-distribution` | 3 | — |
| Priorities | `/priorities/master` | 3 | — |
| Programme Learning | `/ia/learning/` | 3 | — |
| Projects | `/projects` | 3 | — |
| Quality Flags | `/quality-checks` | 3 | — |
| Recruitment | `/recruitment` | 3 | — |
| Verification Queue | `/ia/verification/` | 3 | — |
| Approval History | `/accounts/approval-history/` | 2 | — |
| Batch Payments | `/accounts/batch-payments/` | 2 | — |
| Candidate Pipeline | `/candidate-pipeline` | 2 | — |
| Closure Quality | `/analytics/closure-quality` | 2 | — |
| Coaching | `/team/coaching` | 2 | — |
| Compensation & Benefits | `/compensation-benefits` | 2 | — |
| Cost Settings | `/cost-settings` | 2 | — |
| Coverage | `/coverage` | 2 | — |
| Dashboard | `/mfi-portal/dashboard` | 2 | — |
| Data Issues | `/mfi-portal/data-issues` | 2 | — |
| Data Quality | `/admin-panel/data-quality-center` | 2 | — |
| Employee Relations | `/employee-relations` | 2 | — |
| Employment Compliance | `/compliance-register` | 2 | — |
| Engagement Log | `/cce-leadership/engagements` | 2 | — |
| Fiscal Year Planning | `/planning/fiscal-years` | 2 | — |
| HR Audit Log | `/hr-audit-log` | 2 | — |
| Health & Safety | `/health-safety` | 2 | — |
| Leave Policies | `/leave/policies` | 2 | — |
| Leave Tracker | `/leave/tracker` | 2 | — |
| Lending Evidence | `/ia/lending-evidence/` | 2 | — |
| Loans | `/mfi-portal/loans` | 2 | — |
| MFI Reports | `/mfi-portal/reports` | 2 | — |
| Measurement Framework | `/ia/framework/` | 2 | — |
| Monthly Portfolio Return | `/mfi-portal/monthly-return` | 2 | — |
| Most Significant Change | `/ia/stories/` | 2 | — |
| My Coaching | `/my-coaching` | 2 | — |
| My Team | `/my-team` | 2 | — |
| Offboarding | `/offboarding` | 2 | — |
| Onboarding | `/onboarding` | 2 | — |
| Organization Structure | `/org-structure` | 2 | — |
| Ownership Transfers | `/ownership-transfers/` | 2 | — |
| Partner Evidence | `/ia/partner-evidence/` | 2 | — |
| Partner Payments | `/accounts/partner-payments/` | 2 | — |
| People Analytics | `/hr-analytics` | 2 | — |
| Performance Cycle | `/hr/performance-cycle` | 2 | — |
| Planning Monitor | `/planning-monitor/` | 2 | — |
| Policies & Documents | `/policies` | 2 | — |
| Priorities | `/priorities` | 2 | — |
| Programme Rollout | `/programme-rollout` | 2 | — |
| Project Capacity | `/projects/capacity` | 2 | — |
| Recognition | `/recognition` | 2 | — |
| Recovery Plans | `/recovery-plans` | 2 | — |
| Returned Activities | `/ia/returned/` | 2 | — |
| SSA Verification | `/ssa/verification/` | 2 | — |
| Sample Checks | `/ia/samples/` | 2 | — |
| Staff Activity | `/staff-activity` | 2 | — |
| Staff Pulse Surveys | `/pulse-surveys` | 2 | — |
| Training Feedback | `/cce-leadership/feedback` | 2 | — |
| Unassigned Schools | `/admin-panel/staff-setup-queue` | 2 | — |
| Users | `/partner/users` | 2 | — |
| Verification Analytics | `/ia/analytics/` | 2 | — |
| Admin My Plan | `/admin-ops/my-plan` | 1 | — |
| Admin Planning | `/admin-ops/planning` | 1 | — |
| BT Overview | `/business-transformation/overview` | 1 | — |
| Business Accounting & Finance | `/business-transformation/business-accounting-finance` | 1 | — |
| Completion Reviews | `/pl/review-queue` | 1 | — |
| Dashboard | `/country-planning-oversight/` | 1 | — |
| Dashboard | `/ia/dashboard/` | 1 | — |
| Data Repair Center | `/data-repair` | 1 | — |
| Disbursement Dashboard | `/disbursements` | 1 | — |
| Duplicate Review | `/ia/duplicates/` | 1 | — |
| Evidence Compare | `/ia/compare/` | 1 | — |
| Finance | `/budget` | 1 | — |
| Government Requirements | `/business-transformation/government-requirements` | 1 | — |
| Impact & Reports | `/business-transformation/impact-reports` | 1 | — |
| Maintenance Calendar | `/admin-ops/maintenance` | 1 | — |
| My Performance | `/team-performance/` | 1 | — |
| My Performance | `/priorities` | 1 | — |
| My Plan | `/projects/my-plan` | 1 | — |
| Partners | `/partners` | 1 | — |
| Planning | `/projects/planning` | 1 | — |
| Regional Lead | `/cce-leadership/feedback` | 1 | — |
| Roles & Permissions | `/admin-panel/roles-permissions` | 1 | — |
| Support Tickets | `/admin-ops/support` | 1 | — |
| System Health | `/system-health` | 1 | — |
| System Incidents | `/admin-ops/incidents` | 1 | — |
| Team Assignments | `/actions/sent` | 1 | — |
| Team Availability | `/leave/team-availability` | 1 | — |
| Team Leave | `/leave/approvals` | 1 | — |
| Team Plans | `/admin-ops/team-plans` | 1 | — |
| Users | `/admin-panel/users` | 1 | — |
| Verification History | `/ia/history/` | 1 | — |
| Weekly Advance Request | `/disbursements` | 1 | — |

## 6.4 Full pages by area

| Area | Pages | Templates |
|---|---|---|
| ia | 22 | activity_timeline, analytics_dashboard, compare_evidence, duplicate_review, framework, impact_reports, impact_reports_brief, impact_reports_detail, learning, lending_evidence, notifications, queue_table, partner_evidence_queue, partner_review, returned_activities, review_workspace, school_evidence, stories, verification_analytics, verification_history, verification_queue, verification_samples |
| accounts | 16 | accountability, activity_evidence, activity_finance_detail, approval_history, audit_log, batch_payments, blocked, budget_amendments, cleared, dashboard, monthly_request, partner_payments, ready_for_advance, returned, variance_review, weekly_requests |
| admin | 14 | audit_log, data_quality_center, duplicate_review, index, notifications_mgmt, page_access_matrix, region_district_setup, roles_permissions, school_upload_history, staff_setup_queue, unmatched_ssa_queue, user_detail, users, workflow_rules |
| hr | 14 | conversation_document, extra_work, hr_today, module_workspace, my_performance, performance_console, performance_conversation, priorities_master, priority_configuration, professional_development_dashboard, pulse_respond, ssa_mapping, target_distribution, team_target_distribution |
| partner | 12 | activities, activity_workroom, assigned_list, assignment_detail, assignments, completed_payments, evidence, invoice_document, my_plan, schools, today, users |
| admin_ops | 11 | _header, _work_section, data_repair, incident_detail, incidents, maintenance, my_plan, planning, report_problem, support_queue, team_plans |
| help | 10 | article, category, edit_article, glossary, index, manage, manual_export, print_article, release_notes, search |
| documents | 9 | _safeguarding_policy_source, agreement_center, canonical_document, compliance, manage_document, new_document, restricted, upload_center, viewer |
| oversight | 9 | cluster_oversight, core_schools_oversight, country_execution_table, country_map, country_planning, country_table, partner_oversight, planning_monitor, team_planning |
| dashboards | 8 | cceo, cd, hr, main, pl, rpl, rvp, special_projects |
| leave | 8 | leave_approvals, leave_calendar, leave_coverage, leave_policies, leave_tracker, personal_time_off, public_holidays, team_availability |
| schools | 8 | closed, detail, import_result, index, ownership_transfers, programme_schools, upload, upload_preview |
| business_transformation | 7 | financial_health, government_requirements, impact_reports, index, loan_application_public, loans, mfi_portal |
| projects | 7 | analytics, capacity, detail, index, monitoring, my_plan, planning |
| ssa | 6 | manual_entry, upload_center, upload_history, upload_preview, upload_result, verification_queue |
| auth | 5 | change_password, login, mfa_verify, request_not_sent, reset_password |
| closure | 5 | activity_closure_detail, activity_timeline, blocked_closure, completed_detail, readiness_queue |
| core_schools | 4 | champion_candidates, champions, detail, index |
| debriefs | 4 | dashboard, detail, submit, weekly_report |
| my_plan | 4 | detail, evidence_packet, index, pl_queue |
| planning | 4 | fiscal_years, index, schedule, visit_requests |
| clusters | 3 | detail, index, profile |
| finance | 3 | country_budget_history, country_budget_submission, fund_allocation |
| settings | 3 | activity_catalogue, index, two_step_app |
| bulk_completion | 2 | batch, upload |
| escalations | 2 | _table, index |
| messages | 2 | index, new |
| partners | 2 | detail, index |
| staff | 2 | detail, index |
| staff_activity | 2 | follow_up, index |
| system_health | 2 | index, notifications |
| team_performance | 2 | country_targets, index |
| acting | 1 | index |
| actions | 1 | workspace |
| analytics | 1 | workspace |
| audit | 1 | decision_log |
| budget | 1 | index |
| budgets | 1 | monthly |
| calendar | 1 | index |
| cce_leadership | 1 | workspace |
| cluster_management | 1 | scoring |
| cost_settings | 1 | index |
| coverage | 1 | index |
| disbursements | 1 | index |
| districts | 1 | index |
| evidence | 1 | index |
| fund_approvals | 1 | index |
| fund_requests | 1 | weekly |
| fy | 1 | index |
| home | 1 | index |
| map | 1 | index |
| my_team | 1 | index |
| notifications | 1 | index |
| (root) | 1 | offline |
| priorities | 1 | guidance |
| professional_development | 1 | index |
| profile | 1 | index |
| profiles | 1 | profile |
| programme_rollout | 1 | index |
| quality_checks | 1 | index |
| reports | 1 | index |
| search | 1 | index |
| targets | 1 | index |
| today | 1 | index |
| todos | 1 | index |
| trainings | 1 | index |
| visits | 1 | index |
| work_plan | 1 | index |

## 6.5 Partials by area

Drawers, tables, cards and rows that pages are assembled from. Each is a piece
of UI to rebuild, usually with its own data and actions.

| Area | Partials |
|---|---|
| dashboards | 73 |
| my_plan | 51 |
| oversight | 49 |
| clusters | 32 |
| schools | 31 |
| country_oversight | 30 |
| country_execution | 24 |
| planning | 23 |
| projects | 22 |
| analytics | 21 |
| core_schools | 19 |
| partners | 18 |
| finance | 18 |
| hr | 17 |
| profiles | 15 |
| targets | 14 |
| ia | 13 |
| staff_activity | 12 |
| messages | 10 |
| trainings | 10 |
| fund_requests | 10 |
| priorities | 9 |
| today | 8 |
| professional_development | 8 |
| team_performance | 8 |
| disbursements | 7 |
| acting | 6 |
| components | 6 |
| business_transformation | 6 |
| fund_approvals | 5 |
| programme_rollout | 5 |
| home | 4 |
| activities | 4 |
| work_plan | 4 |
| calendar | 3 |
| debriefs | 3 |
| cost_settings | 3 |
| ssa | 3 |
| leave | 3 |
| vendor | 3 |
| data_quality | 2 |
| admin | 2 |
| catalogue | 2 |
| notifications | 2 |
| connectivity_status.html | 1 |
| _back_link.html | 1 |
| cost_preview.html | 1 |
| upload_result.html | 1 |
| pwa_head.html | 1 |
| pwa_launch.html | 1 |
| _search_icon.html | 1 |
| _section_nav.html | 1 |
| refusal_drawer.html | 1 |
| evidence | 1 |
| decisions | 1 |
| exports | 1 |
| partner | 1 |
| budgets | 1 |
| actions | 1 |
| documents | 1 |
| todos | 1 |
| coaching | 1 |
| help | 1 |

## 6.6 How a page is rebuilt

Decided on 2026-11-10: the existing application feeds the native screens, and
the CCEO's screens come first.

1. Open the page on the local copy at phone width, in both themes. Read its
   template, its partials and its stylesheet, and sample the computed styles.
2. Find the service the view renders from. Add its view-model to
   `platform/proto/edify/screens/v1` as messages and one RPC per request the
   page makes.
3. Add a feed in `apps/mobile_feed` that calls that same service behind the
   page's own permission check and returns the fields. No rule is written
   there. Test it against the service.
4. The gateway serves the RPC by fetching the feed with the caller's token and
   decoding it strictly against the contract (`internal/feed`,
   `internal/screens`).
5. Build the screen in React Native from the theme tokens and the server's own
   icons (`SvgIcon`). Wording comes from the feed or is copied from the
   template.
6. Compare with the web page side by side in the browser, then on the iPhone
   simulator and the Android emulator.
7. Add the path to `NATIVE_PATHS` in `App.tsx`. Until then the menu opens the
   page on the web and marks it so.

When a page's rules are ported to Go, step 4 changes and nothing else does.

## 6.7 The CCEO's screens, in order

31 destinations. Done: sign-in, the shell (top bar, role bottom bar, full
menu), Home, and the School Directory (read view, 2026-11-10).

| # | Screen | Path | Why here |
|---|---|---|---|
| 1 | School Directory writes | `/schools` | Native (2026-11-10): Add to Cluster, Change Cluster, Add to Project, Select page and the bulk bar's Assign cluster and Assign project. Still to come: Match staff, Reassign owner, Add School, and the actions of other roles (Schedule, Take This School) |
| 2 | School profile | `/schools/<id>` | Native (2026-11-10): header, badges and buttons, all seven tabs (Overview, SSA, Participation, Academic, Stories, Projects, Details), year and period filters; the directory's school names open it. Read from the page itself (§6.10). Every header button's drawer is native: Edit Details, Close School and Enter SSA Score (§6.11), Schedule and Assign to Partner (§6.12), Add to Project |
| 3 | My Plan | `/my-plan` | Native (2026-11-10): header and Export, period tabs with More and Open Calendar, filters with More, Plan progress, Planned and remaining (loaded after, as on the web), every table of work with its count, green/red rows, coloured status words, tick ids and each row's Actions menu, pagers, Cluster Planning Status, Plan Breakdown by Period. Read from the page itself (§6.10, §6.13). Still to come: the row actions' drawers and the Reschedule / Cancel bar |
| 4 | Activity detail and its drawers | `/my-plan/<id>` | Schedule, edit, reschedule, cancel, complete |
| 5 | To-Do | `/todos` | Home's Priority actions and "To-Dos" open it; 14 roles |
| 6 | Dashboard | `/dashboard` | First Quick access shortcut; opened by Home's first action |
| 7 | Calendar | `/calendar` | 14 roles |
| 8 | Clusters and cluster page | `/clusters` | Quick access; cluster scheduling |
| 9 | Core Schools, Programme Schools | `/core-schools` | Daily section |
| 10 | Messages, Notification centre | `/messages` | Top bar and fourth tab |
| 11 | My Actions, Field Debrief | `/my-actions` | Daily section |
| 12 | Weekly Advance Request, Budget | `/fund-requests` | Weekly section; money, so built with extra comparison |
| 13 | Planning, Work Plan, Priorities | `/planning` | Planning cycle section |
| 14 | Oversight pages a CCEO sees | `/cluster-oversight` | Four read-only pages |
| 15 | My Performance, Targets, Coaching, Agreement, Development | `/my-performance` | Monthly section |
| 16 | Leave, Decision Log, Escalations, Extra Work, Loans, Closed Schools | `/leave` | The rest of the menu |
| 17 | Settings, profile, help | `/settings` | Account |

Writes (scheduling, completing, requesting money) go through the existing
application's own endpoints by the same method, one action at a time, each
with its confirmation and error states matched to the web.

## 6.8 Known differences from the web, on rebuilt screens

| Screen | Difference | Why |
|---|---|---|
| School Directory | The bulk bar's Match staff and Reassign owner open the web app | Not native yet |
| School Directory | Add School, Export and the other roles' actions open the web app | Not native yet |
| Drawers | A form select drops its choices below the field in the Edify menu style; on a phone the web shows the browser's own picker for a `<select>` | Follows the owner rule that every dropdown opens at its control and drops down (2026-09-27) |
| School Directory | Add to Project's start date is typed as YYYY-MM-DD | The web's Edify calendar picker is not rebuilt yet |
| Home | Figures, priority actions and shortcuts open "still on the web" screens | My Plan, To-Do and Dashboard are not rebuilt yet |
| Profile drawers | Dates are typed as YYYY-MM-DD (Edit Details, Close School, Schedule) | The web's Edify calendar picker is not rebuilt yet |
| Assign to Partner | A project's hand-over button ("Or assign through a project") opens that project's drawer on the web | The project hand-over drawer is not native yet |
| My Plan | A row's actions (View Details, Reschedule, Start, Complete, Evidence, Cancel), Export and Cluster Planning Status's Schedule open the activity's page or My Plan on the web | Their drawers are not native yet |
| My Plan | Ticked rows have no Reschedule / Cancel bar yet; the tick ids are read (`pick_id`) | The bar comes with the activity drawers |
| Schedule, Assign to Partner | The confirmation has no Undo and no "Open My Plan" link | Undo and My Plan are not native yet; the plan is saved the same way |
| Schedule, Assign to Partner | An empty required field is named in the field's own words ("Please select an item in the list.") rather than the browser's bubble | React Native has no form bubble; the post is stopped the same way |
| School profile | A figure's records (`what=`), Needs Attention lines and links to clusters, districts and staff open on the web | Those pages are not rebuilt yet |
| School profile | The title wraps where the text runs out; the web balances its two lines | React Native has no balanced wrapping |

### Dropdowns and drawers (2026-11-10)

Matched to the web at phone width, measured from the running page:

- **Dropdowns** (`ui/Dropdown.tsx`, placement in `ui/dropdownPlacement.ts`,
  tested): open at their button and drop down below it, 6px under it, never
  flipped up and never from a fixed spot. Row Actions, More filters and
  More views line up with the button's right edge; Export with its left edge;
  selects take the field's width (at least 176px). Near the foot the page
  scrolls up to make room; past that the panel scrolls inside, clear of the
  bottom bar. Panels are drawn in a `DropdownLayer` in the button's own
  window (the app, or a drawer), not a pop-up window: Android measured the
  pop-up from the top of the screen and the button from below the status
  bar, so menus landed one status bar too high. Row menu: 44px entries, 13px semibold, 4px padding, 12px
  corners, the web's shadow. Views menu: 32px entries with count pills.
- **More filters**: a 272px panel of four 32px centred selects (Partner type,
  Cluster status, Missing detail, Project status), 14px padding, 16px corners.
- **Filter selects**: 32px, 12px medium text centred; Sub-county is greyed
  until a District is chosen.
- **Drawers** (`ui/Drawer.tsx`): the web's phone drawer (type-center): a card
  20px in from the sides, at most 84% of the screen tall, 16px corners, over
  a rgba(28, 44, 68, 0.58) backdrop; it fades in and grows from 96% over
  340ms. 15px bold title, a 36px round close button, "* Required
  information", the two-button toggle, 13px semibold labels, 40px fields with
  16px text, an amber confirmation box, and a footer of 36px buttons.

### Profile drawers

- A refused save scrolls the drawer back to the top, where the web's reason is
  drawn (a long drawer used to keep the reason out of sight).
- Directory rows on the web build: the ID pill's button keeps its own width
  when the name beside it is a link (web reads `flex: 0` as zero width, which
  drew the name over the ID).

## 6.9 How a write is rebuilt

The web drawer's view keeps its rules (validation, eligibility, messages,
audit, notifications). Its body becomes `<action>_flow(request, id, respond)`;
the web view calls it with Django's `render`, and the feed calls it with a
responder that returns the outcome's template and context. The feed maps the
outcome to the contract: the success toast is "saved" with its message, the
drawer error is "refused", a re-rendered drawer is "error" with its
validation message. Proven on Add to Cluster and Add to Project: the 324
existing tests of the 16 modules that use those drawers pass unchanged, and a
native save on the development database opened the same membership row.


## 6.10 Pages read as their components

The profile pages (school, cluster, district, sub-region, partner, staff)
draw everything through shared components, and most of their wording lives
in the templates, so a hand-made view-model would retype it and drift. Their
feeds instead run the page's own view for the reader (as a browser request
would, nothing saved) and read the HTML it renders into blocks
(`apps/mobile_feed/page_blocks.py`, Python's own parser, no new dependency):

| Web component | Block | Drawn by (`platform/mobile/src/ui/page/`) |
|---|---|---|
| `edify-back-link`, `edify-page-header` (title, pills, buttons) | header | `SchoolProfileScreen` |
| `[data-profile-tabs]` | tabs | `SchoolProfileScreen` tab rail |
| `[data-profile-scope]`, `[data-profile-identity]` | scope line, facts | `PageBlocksView` |
| `form.edify-filter-bar` | filters | `PageBlocksView` (dropdown selects) |
| `section.context-metrics` | strip | `PageStripView` (two tiles a row) |
| table cards (`edify-table-titlebar` + table or empty state) | table | `PageTableView` (scrolls sideways, swipe hint) |
| `section.edify-data-chart` (its JSON data) | chart | `PageChartView` (cut-out bars) |
| `aside[data-insight-rail]` | rail | `PageRailView` |
| `edify-surface rounded-surface` cards | panel | `PagePanelView` |
| `[data-edify-tablist]` with its parts | segments | `PageBlocksView` |
| `edify-empty-state` | empty | `PageTableView` `EmptyState` |

Only these components are read; anything else is left out, never guessed.
The contract is `edify.screens.v1` `page.proto`. A link stays native when it
only changes the page's own tab, year or period, opens another school's
profile natively, and otherwise opens the web. Tests: `test_page_blocks.py`
(markup to blocks) and `SchoolProfileFeedTest` (the real page, scope, 404).


## 6.11 Drawers read as the web draws them

Edit Details, Close School and Enter SSA Score are the web's own drawers,
rendered for the reader by their views and read into items
(`apps/mobile_feed/drawer_blocks.py`): notes, headings, text, figures and
fields, each with the condition the drawer's script shows it under, the
choices a field reloads (District → Sub-county → Parish) and the choices tied
to another field. A save posts the drawer's own fields and the hidden values
the web rendered to the view that saves it, and the answer is read as the web
reads it: the drawer closing or a success message is saved; the drawer drawn
again carries its errors. Only the drawers the feed names are reachable
(`SchoolDrawerFeedView`), and the web's scope refusal is passed on (403/404).
The app draws them with `ui/WebDrawer.tsx` and its logic `ui/drawerLogic.ts`
(tested). Typed changes ask "Discard your changes?" before closing.

## 6.12 Planning drawers: the script ported

Schedule visit and Assign to Partner build their fields with Alpine: a Training
list for In-school Training, the training followed up for a Follow Up, hidden
values the chosen training fills (catalogue item, activity type,
intervention), purposes and trainings greyed for the date's financial year,
a training ceiling read when the training or the date changes, and fields
cleared when the purpose changes. Reading the rendered HTML alone cannot give
that, so:

- **What the script starts from** is read from the form's `x-data`, which
  Django writes as JSON (`apps/mobile_feed/planning_drawers.py`): the
  training list, partner courses, follow-ups, visit and training locks by
  year, purpose profiles, SSA priorities, the recommended purpose, training
  and intervention. The parts around them (labels, placeholders, helper
  lines, notes, the SSA evidence, the "already has plans" warning and its
  buttons, Facilitated by, the responsible person) are read from the drawer.
- **What the script does** is ported getter by getter to
  `platform/mobile/src/ui/planning/planningLogic.ts` (tested): which parts
  show, which purposes and trainings grey, what a change clears, exactly what
  the form posts (a field the script removed or disabled is not sent), the
  submit button's `:disabled`, and the browser's stop at an empty required
  field.
- **The save** posts those values, plus the hidden values the web rendered,
  to the view the form posts to (`schedule_action_view`,
  `assign_partner_action_view`); only the drawer's own field names pass
  (`SAVED_FIELDS`). The confirmation is the toast card's sentence.
- **The ceiling** is the web's own `/planning/training-capacity` read.

The contract is `planning_drawer.proto` (`PlanningDrawerService`). Checked
against the web drawer at phone width, on the browser, iPhone and Android:
same parts in the same order with the same words. Tests:
`test_planning_drawers.py`, `PlanningDrawerFeedTest` (the real views,
including a schedule saved and a refusal), `planningLogic.test.ts`, and the
gateway's path and input checks.


## 6.13 More components read (My Plan, 2026-11-10)

The page reader (`page_blocks.py`) learned My Plan's components, so the next
pages built from them come for free:

| Web component | Block / field | Drawn by |
|---|---|---|
| `edify-page-eyebrow`; a header link styled `btn` (Export) | header `eyebrow`, an action | `MyPlanScreen` |
| `nav[data-edify-tablist]` of link tabs + `data-edify-beside-link` | `linkTabs` (tabs, beside) | `PageLinkTabsView`: first and open tab, the rest under More, square calendar button |
| `form[data-component=filter-toolbar]` | `filters` with its hidden values | `PageFilterBar`: three in the row, the rest under More |
| a plain `card` with a heading row over its table | `table` with `title`, `count` or summary line | `PageTableView` |
| `tr[data-done]` / `tr[data-overdue]` / `.mp-dayoff-row` | row `tone` | green tint and ink / red ink (row-state.css) |
| `.mp-badge--<tone>` | cell `badge`, `tone` | coloured word, as the plain table draws it |
| `[data-record-action]` with `.row-menu` | cell `actions` (button / menu / danger) | `RowActions`: own button, Actions dropdown |
| `.school-plan-table__select` tick box | row `pickId`, `pickLabel` (column dropped) | — (the bar is next) |
| `edify-empty-state` with its link | table `emptyAction` | one-line empty state with "Open Planning →" |
| `nav.edify-pagination` | table `pager` | page buttons; a page's link is its whole query |
| a `card` of tiles (`p.uppercase` over a figure) | `strip` with `subtitle` | titled card of tiles |
| `[hx-trigger=load][hx-get]` | the part read in its place | feed's `later` (only `/my-plan/readiness`) |

The feed (`MyPlanFeedView`) passes only the page's own parameters (period,
year, quarter, month, filters, `*_page`), never `export`; the gateway refuses
any key that is not a plain word or a value over 64 characters. Tests:
`MyPlanComponentsTest`, `MyPlanFeedTest`, `TestMyPlan*`, `myPlanLinks.test.ts`.

## 6.14 Every role's pages, and the parts read since (2026-11-10)

The feed draws 127 pages (`NATIVE_PAGES = CCEO_PAGES | ROLE_PAGES`), every
sidebar page of every seeded role that opens for that role. `NavItem.native`
marks a page the feed draws *and* the reader may open; the app routes by it.
A menu link a role cannot open goes to the web, which sends the reader on
(the Regional Program Lead's Country Map and Country Planning Oversight).

| Part of the web | Read as | Module |
|---|---|---|
| A card that opens in place (`data-row-disclosure-summary`): clusters, projects | `PageRecord`: name, pills, Actions, facts, details, the list it loads once opened | `records.py` |
| A table's hidden details row | `PageRow.details` / `detail_blocks` / `details_href`, opened under the row | `page_blocks._row_details` |
| A list's own pager (`edify-pagination-scope`) | `PageBlock.pager` | `page_blocks._scoped_pager` |
| Tabs that set the filter form's field and send it (Planning) | link tabs to the form's values with that field changed | `page_blocks._form_tabs` |
| A POST form on the page (Escalations) | `PageForm`, saved through `SaveDrawer` with the form's key; `can_save` else "Continue on the web" | `page_forms.py` |
| A closed dialog (`role=dialog`, `aria-modal`, a full-screen overlay) | `PageDialog`, opened by `#dialog=<flag>` as a sheet | `dialogs.py` |
| The bar for ticked rows (activities, schools) | `PageSelection`; the app draws the tick column and the floating bar | `selection.py` |
| Boxes sharing a name (incl. Alpine `x-for` over `x-data`) | one `checklist` field | `checklists.py` |
| Radio buttons sharing a name | one `radio` field, drawn as pills | `checklists._radio_group` |
| A date field | the Edify calendar (`DateField`), `min_date` / `max_date` | `calendar.ts`, `DateField.tsx` |
| An export drawer | saved to `/exports/prepare`; `ExportService.GetExport` then a five-minute signed download link the phone's browser opens | `exports.py` |

Hidden on opening and so not drawn: a part shown only once a list fills
(`x-show="selected.length > 0"`), a closed dialog, the bar for ticked rows,
the phone's fold around the filter bar.

**The gateway decodes the feed strictly.** A key the contract does not know
fails the whole screen, and neither the feed's tests nor the gateway's can see
it. `python manage.py gateway_smoke --settings=config.settings.dev` walks every
seeded role's menu, each native page and a school profile through the running
gateway (442 pages, 0 failures, none over 3 s on 2026-11-10).

Still on the web: file uploads (a native picker needs `expo-document-picker`,
not yet added), downloads other than the export drawers, forms whose view the
feed does not save through yet (they say "Continue on the web").
