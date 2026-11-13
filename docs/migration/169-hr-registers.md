# 169. The HR registers, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". About twenty
Human Capital pages are one register shell
(`apps.frontend.views.hr_views._render_workspace`,
`pages/hr/module_workspace.html`, `partials/hr/module_register.html`) filled
by a view each. `platform/backend/internal/hrregister` ports the shell and the
reach rule once; each register is added to it as it is ported.

| Register | Path | State |
|---|---|---|
| Organization Structure | `/org-structure` | This document |
| The other registers (onboarding, offboarding, recognition, pulse surveys, health and safety, employee relations, compliance, compensation, candidate pipeline, recruitment, workforce planning, performance reviews, policies, HR audit log, HR analytics, recovery plans, …) | | Still the existing application's; each is a backlog item that adds a builder |
| Every save a register's buttons open | | Still the existing application's |

## 169.1 The shell

| Part | Existing rule it ports |
|---|---|
| Who may open a register | `require_page_permission(<the register's permission>)` and the feed's `can_open_url`, exported per role. Anyone else is not found, as the feed answers |
| Header | The register's eyebrow, title and description; each drawer button the role's `can_open` admits (exported per role). Link buttons (HR overview, the primary action) are not read by the feed |
| Breadcrumb | "Human Capital" (to `/dashboard`), "/", the title |
| Strip | The workspace strip the role is shown, rendered and read by the feed's own reader at export |
| Context figures | `components/context_metrics.html`: each figure once by its label, under the label the metric registry draws it with; the line under it kept only when it is a short second figure (`brief_helper`, shared with the school profile's strips), else moved to the note; the figure's tone only beside a line that stays |
| Records | "Current operational records"; while a search (`q`, stripped) is on, a "Clear search" link back to the register; the records 50 a page (`page`), or the register's empty title and body |
| Pager | The register's own pager, as the feed reads it: "Page N of M", then Prev and Next, each a link keeping the search (`?q=<|urlencode>&page=N`) and read again as its two words without a link |
| Reach | `apps.hr.reach.people_reach`: Admin or a superuser reads the organisation; the Regional HR Director the countries of the regions their geography assignments name (directly or through a district), else the country on their own People record, else nothing; a Programme Lead their own team (themselves and those whose supervisor they are); anyone else the country on their own People record, else nothing. Someone working in an acting appointment is passed on to the existing application, as every Go page does |

## 169.2 Organization Structure

`org_structure_view`: the live People records of live accounts in reach and
in the search (name, email, title, department or country, case-insensitive),
not exited, by department (none last) and name. Each row: the name, the title
(else the active role), whom they report to (supervisors' names, sorted, else
"No line recorded"), how many report to them, department, country and the
lifecycle state's label. Figures: People in scope, Active, Departments
(distinct, not blank), No reporting line (no supervisor and not a Country
Director, Regional Vice President or Admin).

## 169.3 Rules, access and proof

The doors, strips and buttons per register and role, the lifecycle labels,
the figures' labels, the line length and the page size are exported to
`internal/hrregister/rules.json` by `manage.py export_hr_register_rules`;
`apps/hr/test_hr_register_rules_export.py` fails when the two differ.

`deploy/db/roles.sql` grants `edify_gateway_ro` a People record's title,
department and lifecycle state (applied to `edify_gorn_dev` and
`edify_gorn_test`; production needs the owner's approval at cutover).

- `cmd/parity -screen page -path /org-structure` for all 29 seed accounts:
  the page as it opens, searches (that find people, by country, by role,
  nobody, with spaces, LIKE's own wildcards) and pages.
- `internal/hrregister/testdata/golden.py` files 62 accounts and People
  records and 40 reporting lines in `edify_gorn_test` (two pages; every
  lifecycle state; titles, departments and none; two lines to one person;
  another country; a deleted record and a deleted account), asks the
  existing feed 14 questions as Admin, HR and Impact Assessment and deletes
  the rows; `internal/integration/hr_register_test.go` compares Go's answers
  whole (`EDIFY_HR_REGISTER_GOLDEN`).

## 169.4 Found

- The feed reads each pager link twice more as plain words ("Next", "›")
  without a link; Go copies it. Cosmetic (OWNER_DEFECTS).
