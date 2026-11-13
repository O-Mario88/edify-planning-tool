# 47 (piece 3a). Planning Oversight's portfolio lens, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. Piece 1 of Planning Oversight
(`docs/migration/47-planning-oversight.md`) gave Go the pages' doors; piece 3
is the lenses other than the Team Plan. This document is its first slice:
the **Team / Country Portfolio** lens (`/team-planning-oversight/?view=portfolio`).
Schools & Coverage, Target Performance and IA's monitor tabs are BACKLOG
`planning-oversight-3b`, `-3c`, `-3d`.

## 47.3a.1 What moved

`PageScreenService.GetPage` for `/team-planning-oversight/` with
`view=portfolio` (stripped, any case) is answered by
`platform/backend/internal/oversightportfolio`, wired after
`planningoversight` in `WithPages` (so a reader the page refuses is still
refused there, and every other lens is still handed on).

| Part | Existing rule it ports |
|---|---|
| Who reads the lens | `team_oversight_lenses(user)["portfolio"]`: the planning page permission and `PORTFOLIO_LENS_ROLES`. Admin, Country Director, Impact Assessment, Program Lead, Regional Program Lead. The Accountant and Human Resources fall back to the Team Plan (handed on); a role the page refuses is refused |
| Lens strip | `_lens_tabs(TEAM_OVERSIGHT_PATH, "portfolio", team_available_lenses(...), country=is_country_reader(user))`, exported per role for both labels ("Country Portfolio" / "Team Portfolio"); a superuser is a country reader whatever the role |
| Header | "Planning Oversight" and the template's two descriptions (country / team) |
| The year | `_period_filters`: `fy` stripped, else the operational FY; a year `int()` refuses (`fy=abc`) is the existing page's 500 and is handed on, as is a month field Python's `isdigit` takes and `int` refuses |
| Plans read | `fy_policy.planning_horizon(fy)` (`schoolplanning.Horizon`): the operational year reads forward through later years |
| Schools | `country_portfolio`: `scoped_school_queryset(resolve_user_scope(user), active_schools())`, the district filter, ordered by name, in the same statement shape Django issues (LEFT OUTER JOIN of region for a country boundary), so schools of one name come out in the same order |
| Owners | `_staff_directory`: an owner id is a StaffProfile id or its User id; the direct reporting line to a Programme Lead (supervisors by name, first one holding the role), a Programme Lead holding schools heads their own column, "Unassigned" / "No Programme Lead" otherwise |
| Planning | `_planning_by_school`: live activities (not `DEAD_STATUSES`) in the horizon's years, counted, visits and trainings by `VISIT_TYPES` / `TRAINING_TYPES`, first planned date, cost lines summed |
| Strip | `_portfolio_kpis` through `render_kpi_item` / `format_value` (`MetricValue.ratio`: `round(n/d*100, 1)` as `{:g}%`; "No schools in scope" with none) and `context_metrics.html` as the feed reads it (sentence helpers become notes; a tone only where a line is shown) |
| Filters | FY, Programme Lead (`_lead_options`: every lead in the rows, with counts, unassigned last), District, Planning state; a select with nothing chosen reads as its first option |
| Columns | `_group`: leads and officers by casefolded name, unassigned last; officers with nothing listed dropped; headings folded from the whole portfolio; each officer's table pages on `portfolio_<officer>_page` (50 rows) with the shared pager |
| Rows | `portfolio_workspace.html`: the School ID cell is the `school_code` token the feed reads as no text ("—" when the school has no code), name link, district or "—", cluster link or "No cluster", "N planned" / "Nothing planned", visits, trainings, "j M Y", "UGX n,nnn" |
| Handed on | `?followup=` (the follow-up panel the page loads), a list of ids (`ids`, `*_ids`), every other lens |

Vocabularies are exported by `manage.py export_oversight_portfolio_rules` to
`internal/oversightportfolio/rules.json`;
`apps/planning/test_oversight_portfolio_rules_export.py` fails when they
differ. Nothing in Django changed.

### A gateway fix found on the way

`internal/screens` refused any page query key with a digit
(`^[a-z][a-z_]{0,39}$`), while the feed passes `^[a-z][a-z0-9_]{0,39}$`
(`apps.mobile_feed.views.QUERY_KEY`). Every pager keyed by a record id
(`portfolio_cmw9p7bwp00t19mekheun_page`, Planning Oversight's `g1_page`) was
answered "This view cannot be opened." through the gateway, whoever built
the page. The key pattern is now the feed's
(`TestPageQueryTakesTheKeysTheFeedPasses`).

## 47.3a.2 What was found by comparing

- The seed holds 699 operating schools, all owned by one officer under
  pl1 (52 distinct names): Admin, CD, IA and pl1 read one lead and one
  officer over 14 pages; pl2–pl4 an empty portfolio.
- Same-name schools: the parity tool sorts same-name runs by the School ID
  cell, which this page leaves empty, so the order compared is the order each
  side gave. Go issues Django's statement shape and matched on every page.
- `COVERAGE_LENS_ROLES` (and so `PORTFOLIO_LENS_ROLES`) names
  `"RegionalVP"`, which is not a role (`EdifyRole.REGIONAL_VICE_PRESIDENT`
  is `"RegionalVicePresident"`): the Regional Vice President gets no
  coverage or portfolio lens. Go follows the existing answer; for the owner.

## 47.3a.3 Parity

Go-only gateway (no existing application behind it) on 127.0.0.1:8081
against the existing application on 127.0.0.1:8181, both over
`edify_gorn_dev`; 33 questions per account
(`cmd/parity/page_oversight_portfolio.go`, run with
`-path '/team-planning-oversight/{id}' -ids ''` because the lens shares its
path with the other lenses' question sets).

Last lines, as printed:

```
957 answers compared, 21 differing
112 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

All 21 differing are answers handed on (`unavailable: This screen is not
available here yet.` from a Go-only gateway), 3 for each of the 7 readers the
lens opens for (admin, cd, ia, pl1–pl4): `followup=abc` (the follow-up panel),
`ids=a,b` (a list of ids) and `fy=abc` (the existing page answers 500). The
22 accounts the page refuses: 0 differing (refused by `planningoversight`).
So of the 957 answers, Go built 936 itself, 210 of them portfolio pages
(7 readers × 30 questions: every year, planning state, lead, district, the
officer's pages 0, 2, 14, 99 and `abc`, alone and under a filter) and 726
refusals; none of them was handed on.

## 47.3a.4 Tests

- `internal/oversightportfolio/page_test.go`: column and officer order
  (casefold, unassigned and no-lead last, emptied officers and leads dropped),
  totals folded before the lead filter, Python rounding of shares and
  ratios, lead coverage tones, the row words, page parameters, the empty
  portfolio, the doors and every question handed on.
- `internal/integration/oversight_portfolio_test.go`: Admin's count of
  operating schools and the officer's second page; a Programme Lead's team
  description; a CCEO refused.
- `internal/screens/plain_query_test.go`: page keys with digits.

## 47.3a.5 What is left

BACKLOG `planning-oversight-3b` (Schools & Coverage), `-3c` (Target
Performance), `-3d` (IA's Planning Monitor and Execution tabs, and the
redirect every other reader gets). The seed cannot show a second lead or
officer, an unassigned school, or a Regional Program Lead: those are unit
tests.
