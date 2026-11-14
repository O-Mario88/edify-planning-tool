# Next: the targets engine, then My Team and My Performance

Status: planned 2026-11-14, nothing built yet. The owner's rule for these two
pages (2026-11-14): Go stays read-only and hands the reader on to the existing
page exactly when Django would write on the read.

## Why the engine comes first

`/my-team` (apps.frontend.views.staff_views.my_team_view, apps.hr.team_roster)
and `/my-performance` (hr_views.my_performance_view) both stand on the target
engine: My Team's Target and Risk columns are Team Targets' FY cell and month
status for each officer (`PLTeamTargetsService._member`), and My Performance
shows each priority's live progress from the validated ledger. The same engine
later serves My Targets and Team Targets. Go has none of it.

## The engine (new package internal/targets)

| Python | Go piece | Notes |
|---|---|---|
| `active_target_areas()` | areas | **writes on read** when an official area row is missing: hand on then |
| `priority_target_areas_for_users` | priorities | latest agreed annual_priorities review per staff (stage not in not_started/priorities_draft/priorities_manager_review), its priorities by sequence, created_at; metric_key → area via PERFORMANCE_METRIC_TO_AREA; target_number > 0; first per area; else the legacy monthly_personal_target areas (target > 0) for users with no agreed review |
| `_explicit_targets`, `_target_profiles`, `_targets_from` | targets | explicit months win; else annual (priority's target_number, else StaffTargetProfile ANNUAL_FALLBACK) split 12 ways, remainder to the early months |
| `refresh_many` | ledger freshness | **writes on read** (rebuilds and clears target_ledger_dirty): any mark for the reader's officers (owner_id = user id or staff id, fy) → hand on |
| `_validated_ledger`, `_achievements_from` | achievements | validated rows, credited_month 1..12, quantity summed |
| `weighted_period_pct` | share | weight-averaged per-area %, areas with no target left out; round() half-even |
| `FinancialYearCalendarService` | calendar | month/quarter/FY ranges and labels; working days = weekdays − public holidays (calendarpage.PublicHolidayDays) − the officer's approved leave days (ISO spans, unparseable skipped); expected pace |
| `team_status_for`, `team_status_display` | status | bands TEAM_ON_TRACK_BAND / SLIGHT / HIGH_RISK (export them) |
| `_member` matrix cells | member | month, Q1–Q4, FY cells: pct, display_pct (None when Upcoming), status, tone |

Export everything that is a constant (area map, fallbacks, bands, official
areas, review stages) from a `manage.py export_targets_rules` with a drift test,
as every other Go module does. Oracle: apps/targets/test_team_targets_oracle.py
fixtures are the cases to reproduce in a golden.

## My Team on top of it (apps.hr.team_roster, 910 lines)

Sources, each one query for the team: team_members (PL seat, acting seat →
hand on), portfolio (operating schools, district majority else home district),
delivery (pl_analytics VERIFIED_STATUSES, NOT_IN_PLAN statuses, completions
awaiting the PL), SSA coverage (confirmed SSA this FY), leave (away now, next,
pending), target bands (the engine), reviews (+ MANAGER_STAGES), PD requests
at the supervisor stage, escalations (escalations package's addressed-to-me
rule, in Go already), extra work submitted to the reader, overdue policy
acknowledgements (READABLE_STATUSES), last coaching (ccelead/teamcoaching.go,
in Go already); needs-action list (HR's _leave_decisions_overdue,
_reviews_overdue, _leave_without_coverage — not in Go yet), summary, KPI strip,
template pages/my_team/index.html. Any source that raises is logged and left
empty in Django; Go must do the same, not fail the page.

## My Performance

`build_draft_agreement` **writes on read** when the FY has a cycle and the
reader no review: hand on then. Otherwise read the agreement, live progress
from the engine, development rows (performance_engine.development_rows) and
values.

## Proof

Goldens in the usual shape (ids prefixed, filed by the integration test), the
oracle's fixtures among them; parity ALL 29 accounts on both paths; the
hand-on cases (a dirty mark, a missing area, no draft yet) asserted to pass on.
