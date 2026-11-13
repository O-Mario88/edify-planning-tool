# 44. The Training Summary, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application's only backend. This is the Training
Summary lens of Team Oversight, as the app opens it.

| Piece | What moves | State |
|---|---|---|
| 1 | The Summary tab of the Training Summary (`/team-planning-oversight/?view=trainings`): the lens strip, the year and Programme Lead filters, the Summary / By staff / Schools strip, and the table of trainings against the Country Ceiling and each officer's ceiling | This document |
| — | The By staff and Schools tabs (`&tab=staff`, `&tab=schools`) | Still the existing application's (backlog item training-summary-2) |
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

- The By staff and Schools tabs (backlog item training-summary-2): Go passes
  them on today.
- `team_planning_oversight_view` reads `team_oversight_lenses` and
  `team_available_lenses` (lifted out unchanged); nothing else in Django
  changed.
- The seed has no Country Ceiling, no officer ceiling and no project training
  with a school, so those figures are proved by unit and integration tests,
  not by parity.
