# 58 — To-Do page: the Project Coordinator and Business Transformation queues

Branch `agent/todos-pc-bto`, cut from `feature/edify-go-rn-migration` with `agent/todos-pl` (doc 55,
not yet merged) merged in first, because both change `internal/todos`.

## What moved

Go (`platform/backend/internal/todos`) now answers `/todos` for the **Project Coordinator** and the
**Business Transformation Officer** too (`PortedRoles` = CCEO, Program Lead, ProjectCoordinator,
BusinessTransformationOfficer). Which builders each role reaches is the exported list
(`rules.json` `roles`), unchanged:

| Role | Builders reached | New in Go |
|---|---|---|
| ProjectCoordinator | 17 | `portfolio_todos.project_school_planning_todos` (built); `attendance_todos`, `evidence_todos`, `fy_planning_todos` opened to the coordinator |
| BusinessTransformationOfficer | 15 | the BT officer's part of `_business_transformation_todos`; `learning_todos` for BT |

### Built
- **Plan Activities for Newly Added Project School** (`schools_awaiting_project_planning`): the
  coordinator's open projects (managed, or an active staff assignment), their newest enrolments at
  operating schools (`current_enrolments`, `-created_at`, row limit × scan factor), less the
  (project, school) pairs with project work not cancelled/rejected/not planned; eight rows.
- **Confirm loan in Salesforce**: loans in the officer's loan scope (`scoped_loans`: the country's
  schools, `school_in_country_q`) pending in Salesforce, oldest submission first, forty. Due three days
  after the submission's UTC day; medium, high from the day before, overdue after, critical a week past.
- **Schedule Loan-Use Verification** (the BT/CD/Admin form: school · lender, `/schools/{code}#school-bt-title`).
- **Review Geographic Financing Gap**: one row for the first twenty districts (by region, name) with
  operating schools and none financed (`DISBURSED_LOAN_STATUSES`), schools written `f"{n:,}"`.
- **learning_todos for BT**: loan impact conclusions due to prepare and those returned to the officer
  (`scoped_impact_loans`, country-bound through the school's region), each one row, critical when the
  oldest is more than a week old.
- The workspace strip: the coordinator's page carries the **Dashboard** strip
  (`partials/_section_nav.html`); exported per role (`roles.<role>.strip`, the decision log's `strip`
  helper), so any role gaining one gets it from the export.

### Guarded (the officer is passed on when there are rows)
Repayment risk snapshots, unreviewed loan-use concerns and requested loan purposes
(`btOfficerGuard`). The guards Go already had (school actions, visit requests, My Targets, PD, field
debriefs, Staff Activity follow-ups) apply to both roles unchanged.

## Rules exported, not restated
`export_todos_rules` gained `pc_bt` (`pc_bt_rules()`): evidence field roles, FY planner roles, open
project statuses, row limit and scan factor, not-planned statuses, the BT loan roles
(`UGANDA_WIDE_ROLES`), impact country(-bound) roles, Salesforce pending, repayment risk statuses,
concern findings, requested purpose, eligible school statuses, disbursed statuses, IA statuses and the
legacy preparer; four link shapes (`/projects/planning?project={id}`, `/loans?open={id}#loan-register-title`,
`/business-transformation`, `/business-transformation/impact-reports`); the per-role strip.
Lifted to module constants (no behaviour change): `todo_service.BT_REPAYMENT_RISK_STATUSES`,
`BT_ELIGIBLE_SCHOOL_STATUSES`; `projects.portfolio.ENROLMENT_SCAN_FACTOR`, `NOT_PLANNED_STATUSES`.
The day thresholds (3, 7, 1, a week) and row limits (40, 30, 20, 500) are literals in the Python and
Go constants in `pcbt.go`.

## What comparing found
- The coordinator's first run differed by one block: the Dashboard workspace strip, which no CCEO or
  lead page has. It is now exported per role.
- The integration database has no loans, so every district there is a financing gap: with the
  geography section only guarded the officer would have been passed on in production too. It is
  built; checked against the existing builder over `edify_gorn_a20_test`: one district (Mukono),
  "700 eligible schools", Go's statement gives 1 district, 700 schools.

## Parity
Go-only gateway 127.0.0.1:8082, existing application 127.0.0.1:8182, all 29 accounts, 5 questions each
(see the report for the last lines exactly as printed). Coordinator and Business Transformation:
0 differing, every answer built by Go. The accounts still passed on are admin, cd, ia and pl1
(items todos-cd-admin, todos-ia, todos-pl-2).

## Tests
- Unit (`pcbt_test.go`): Salesforce priority by age (seven days around the due day), the learning
  row's lateness and plural, `f"{n:,}"`. `TestEveryBuilderGoHasIsOneOfTheQueues` now covers both roles.
- Integration (`todos_pcbt_test.go`): the coordinator's strip and rows, rows gone when the projects are
  paused; BT's financing gap row; BT passed on with a requested loan purpose.

## Left
- Golden comparisons on synthetic rows for the guarded BT sections (repayment risk, loan-use concerns,
  purpose proposals), then build them.
- `learning_todos` / `_business_transformation_todos` for IA and CD (items todos-ia, todos-cd-admin):
  `learningTodos` passes every other role on.
