# 44. The Training Summary, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application's only backend. This is the Training
Summary lens of Team Oversight, as the app opens it.

| Piece | What moves | State |
|---|---|---|
| 1 | The Summary tab of the Training Summary (`/team-planning-oversight/?view=trainings`): the lens strip, the year and Programme Lead filters, the Summary / By staff / Schools strip, and the table of trainings against the Country Ceiling and each officer's ceiling | This document |
| 2 | The By staff and Schools tabs (`&tab=staff`, `&tab=schools`): each person's trainings against their ceiling, and the school-level coverage table with its Training, Staff and Show filters | 44.8 |
| — | Every other lens of Team Oversight, a page opened from a planning follow-up (`&followup=`), the ceiling drawers and the schools drawer | Still the existing application's |

## 44.1 What the app's feed opens

`apps.mobile_feed.views.ROLE_PAGES` names `team_planning_oversight`
(`/team-planning-oversight/`). The page is gated by
`require_any_page_permission("team_planning_oversight", "team_targets")` and
the feed's `can_open_url`; the lens by `can_view_trainings` (the planning page
permission and a role in `training_summary.SUMMARY_ROLES`). Of the seed
accounts, Admin, the Country Director, Impact Assessment and the four
Programme Leads read it; every CCEO, Business Transformation and the Project
Coordinator are refused the page (404). A role that opens the page without
the lens (Accountant, HR, Regional Programme Lead, Regional VP) is drawn
another lens by the view, so Go passes it on.

## 44.2 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/trainingsummary` for `/team-planning-oversight/`
with `view` reading `trainings` (stripped, any case), for someone working in
their own role, on the Summary tab. Everything else under the path is passed
on (`served=false`).

| Part | Existing rule it ports |
|---|---|
| Who may open it, and the lens strip | `team_oversight_lenses` and `team_available_lenses` (lifted out of `team_planning_oversight_view` unchanged, so the view and the export read one answer), `_lens_tabs`, `is_country_reader` (role, or a superuser) |
| The year | `fy` stripped, kept if one of `fy_options()`, else the operational FY |
| Whose columns | A Programme Lead: their own profile, then the live CCEOs they or a Programme Lead they cover supervise, by name (`ceiling_staff_options`, `team_roster._read_team_members`). A reader of the country: the country's live CCEOs and Programme Leads (`country_officers`), each Lead followed by their officers (`_leads_of`, `_teams_in_order`), narrowed to one Lead's team when `program_lead` names a Lead |
| Which trainings | `country_scheduled` over every staff identity of the country: schools on group trainings (`_group_rows`), staff in-school trainings (`_in_school_rows`), partner trainings (`_partner_rows`, with `dated`) and open hand-overs (`_handover_rows`, read only in the running and later years), outside projects and never a live project's training; then the catalogue entries by display name and code |
| The figures | Total Covered (each school once), Staff Planned, Awaiting Partner, Remaining, the Country Ceiling (`country_ceilings`); each column's schools and ceiling (`summary_for_staff`, `TrainingCeiling`); project trainings from `project_training_mappings`, `ProjectSchoolAssignment` and `ProjectStaffCapacity` (`_project_rows`) |
| Tones and links | `Cell.tone` and `Row.country_tone`, exported; the links of `_country_figure.html`, `_country_ceiling_cell.html` and `_summary_cell.html` |

The statements are the ones Django issues (printed with
`sql_with_params()`), including the `NOT IN` of the project trainings and the
inner joins to `school`.

## 44.3 Rules

Exported by `python manage.py export_training_summary_rules` to
`internal/trainingsummary/rules.json`; `apps/planning/test_training_summary_rules_export.py`
fails when they differ: every role's doors and lens strip (country and team
labels), the training and meeting types, `MeetingKind.TRAINING`, the released
statuses, `PLANNED_STATES`, the partner delivery value (read from
`partner_delivery_q` itself), `DATED_BY_PARTNER`, the certified agency, the
open hand-over statuses, the live project statuses, the modes of delivery and
the catalogue's (`_CATALOGUE_MODES`, else the method's label), the country
reader roles, the default country, the tones, and how the feed passes a query
(`QUERY_KEY`, `NOT_PASSED`, `MAX_QUERY_VALUE`). The words are the templates',
written in Go.

## 44.4 Grants

Appended to `platform/deploy/db/roles.sql` and applied additively to
edify_gorn_dev and edify_gorn_a22_test: `activity (partner_date_set_by,
executor_type)`, `activity_catalogue_item (activity_type)`,
`activity_project_mapping (catalogue_item_id, project_id, active)`,
`partner_assignment (source_activity_id, catalogue_item_id)`, `"user"
(is_superuser)`, `training_ceiling (id, staff_id, training_id, ceiling, fy)`,
`training_country_ceiling (id, training_id, ceiling, fy, country)`. Read only.

## 44.5 Proof

Parity (`cmd/parity/page_training_summary.go`, 22 questions an account: the
lens with stray spaces and capitals, every year offered and three that are
not, the Summary tab named and a tab that is not one, each Programme Lead's
team, one with stray spaces and one that is no Lead, `export` and `format`,
filters together), Go-only gateway on 8084 against the existing feed on 8184,
both over edify_gorn_dev. Results in 44.6.

Unit tests cover what the seed cannot reach: ceilings set (above, at, below
and unset, with their tones), Admin's Set and edit links, a Lead's ceiling
edit link, the country figures' links, project trainings, the flag counts in
the subtitle, both empty states, `intcomma` past a thousand, the query the
feed passes, hand-overs by year, and team order. The integration test files a
hand-over and a Country Ceiling on the test database and reads them as Admin
and a Programme Lead; a CCEO is refused.

## 44.6 Parity numbers

All 29 seed accounts, `-pause 20s`, 2026-11-13 (the first full run was cut at
the eighteenth account when the shared PostgreSQL was shut down at 13:05; its
first 17 accounts were 0 differing; the run was repeated in full once it was
back). Last lines, as printed:

```
coordinator@edify.org              22 questions, 0 differing

638 answers compared, 0 differing
126 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

## 44.7 What is left

- ~~The By staff and Schools tabs~~: Go's since piece 2 (44.8).
- `team_planning_oversight_view` reads `team_oversight_lenses` and
  `team_available_lenses` (lifted out unchanged); nothing else in Django
  changed.
- The seed has no Country Ceiling, no officer ceiling and no project training
  with a school, so those figures are proved by unit and integration tests,
  not by parity.

## 44.8 Piece 2: the By staff and Schools tabs

Backlog item training-summary-2. `internal/trainingsummary` now answers
`tab=staff` and `tab=schools` (stripped, any case) as well; anything else
still opens the Summary tab, as the view does. Both tabs read the summary
with `with_rows=False` (the readers and columns only: Go skips the Summary's
rows the same way).

| Part | Existing rule it ports |
|---|---|
| By staff rows | `training_ceilings.summary_for_staff(summary.staff, fy)`: one row per person and training with a ceiling or a school committed; each route's schools as sets (a school once); `both` from `_counted_twice`; ceilings of a project's training dropped; ordered by name, then training |
| By staff figures | `SummaryRow.total`, `awaiting_partner`, `balance` ("View" when unset), `excess`, `state`, `flag` and `flag_tone` (exported); `summary_totals` for the line beside the title; every figure links `/training-summary/schools?…&figure=`; `coverage_by_staff.html`'s muted 0, warning Awaiting, strong Schools Covered and red Excess |
| Who the Schools tab lists | `training_summary.coverage_profiles`: the summary's columns, or for a reader of the country with no Lead chosen every staff profile of the country (and of none), left staff included |
| Schools rows | `training_coverage.table` over `commitments` (group sessions, staff in-school trainings, partner trainings with `dated`, open hand-overs, each one row per school and session; Partner names from `Partner.all_objects`), `_status_of`, `next_action`, `href`, `_in_order` and `_remark` (the second row of a school for one training and officer is "same school, counted once"), `_of_figure` for Show, and with a training chosen `uncovered` (operating, trained-type, non-duplicate schools the person holds that have no commitment), statuses counted before the table is narrowed |
| Schools filters | Training (`trainings_committed` over the same people), Staff (the summary's columns), Show (`SHOW_OPTIONS`); a value no option carries reads as the first option, as the feed reads a select |
| Pagers | `{% paginate %}` at `TABLE_PAGE_SIZE` with `by_staff_page` / `coverage_page`, clamped, `{% pager_query %}`, the pager's summary standing in as the note (the feed reads the first `<p>` under the table) |
| Names | `staff_link`: a link to `/staff/<id>` for a role that may open a staff profile (`opens_staff_profile`, exported per role); the School ID cell is the `{% school_code %}` token the feed reads as nothing |

The four statements copy Django's (`sql_with_params()`), including their
`ORDER BY` (attendance by school name, activities and hand-overs newest
first) and the `uncovered` statement's `ORDER BY name`, so rows Python's
sort leaves tied come back in the same order.

Rules added to the export (`coverage` and `doors.*.opens_staff_profile`):
route labels, status labels, order and tones, Show options, figures, the
completed and under-way activity statuses, trained school types, excluded
duplicate statuses, operating statuses, `TABLE_PAGE_SIZE`, and the summary
flag tones. The words are the templates', written in Go.

Grant (appended to `roles.sql`, applied additively to edify_gorn_dev and
edify_gorn_a23_test): `school (duplicate_status)`, the filter `uncovered`
applies. Read only; nothing the secrets test refuses.

### Proof

Parity questions added to `cmd/parity/page_training_summary.go`: each tab
spelt with stray spaces and capitals, other years, each Lead's team, pages
in and out of range (By staff 0, 2, "x"; Schools 2, 7, 14, 99 and " 3 " over
the 660 rows a chosen training lists), every training committed and one
that is not, alone and with Show=remaining, a staff member, a Lead and
someone unknown, every Show value and one that is not. Go-only gateway on
8085 against the existing feed on 8185, both over edify_gorn_dev.

All 29 seed accounts, 71 questions an account (the 22 of piece 1 and 49
new), `-pause 20s`, 2026-11-13. Last lines, as printed:

```
coordinator@edify.org              71 questions, 0 differing

2059 answers compared, 0 differing
229 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

The gateway had no existing application behind it, so all 2,059 answers
were built by Go (refused readers' 404s included).

Unit tests (`tabs_test.go`) cover what the seed cannot reach: a ceiling
above, at and below (with `intcomma`), the excess in red, every status and
next action of a commitment (staff, group, partner dated and not, in
progress, completed, not covered), a school on two sessions marked once, the
Awaiting figure with a school the Partner has dated once, both empty states,
singular "school", the pager at 120 rows and its window. The integration
test `TestTheTrainingSummaryTabsReadAHandoverAndACeiling` files a hand-over
and a Lead's own ceiling on the test database and reads both tabs.

### What is left

- The seed's commitments are one staff-planned training and three partner
  hand-overs (FY 2027; the hand-overs again in FY 2028, none in 2025 or
  2026), and no officer ceiling: group sessions, partner-dated, in-progress
  and completed rows and every ceiling state are proved by unit and
  integration tests only. Not Covered rows and the pager are proved by
  parity (a chosen training lists 660 rows).
- The schools drawer (`/training-summary/schools`, `schools_behind`) every
  figure opens, and the ceiling drawers, stay the existing application's.
