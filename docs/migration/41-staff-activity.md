# 41. The Staff Activity Log, read by Go

Backlog item `staff-activity` (read): the Staff Activity Log page
(`/staff-activity`), the owner's 2026-09-29 replacement for Who's Online.

| Piece | What moves | State |
|---|---|---|
| 1 | The log for the Country Director and the Admin; a Programme Lead sent to their dashboard; the roles it refuses | This document |
| — | A person's detail (`/staff-activity/people/<id>`), the export, the follow-up drawers and saves, the heartbeat | Still the existing application's |
| — | The Programme Lead's copy on their dashboard (`/dashboard#staff-activity`) | Still the existing application's (the dashboard is) |

## 41.1 What moved

`PageScreenService.GetPage` for `/staff-activity` is answered by
`platform/backend/internal/staffactivity` for anyone working in their own
role. Go builds the blocks the existing feed reads from
`pages/staff_activity/index.html` and `partials/staff_activity/`:

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("staff_activity")` and the feed's `can_open_url` (exported per role): Admin, Country Director, Impact Assessment, Program Lead. Anyone else is not found |
| A Programme Lead | `dashboard_embed.reads_on_dashboard`: the feed's redirect to `/dashboard?sa=<the page's own query>#staff-activity`, the query's `fy` carried as the dashboard's year |
| A role the page admits but whose log is nobody's (Impact Assessment) | `viewer_scope` is None and the view answers 403: the gateway answers `PermissionDenied`, as the feed's 403 is read (new `pagegate.ErrForbidden`) |
| Whose log | `country_roster_ids`: every active, live CCEO and Programme Lead in the reader's country (the reader's first live staff profile by id; every one where it has none), the reader left out |
| The period | `presence_period` + `activity_period`: day, week (Monday–Sunday), month, operational quarter, FY; an unknown period is a day; `date.fromisoformat` (3.13: `YYYY-MM-DD`, `YYYYMMDD`, ISO week dates) else today; labels as the page writes them; the days that have happened |
| A row | `_people`: sign-ins in the period, the first and last active time (sessions active in the period), active time by part of the platform plus the time since the last beat as the next beat credits it (`_credit_for`), where the person is now (Online within the online window, Idle within the session age on a page, Offline, signed out, On approved leave), expected working days (weekdays, not public holidays, not approved leave), meaningful actions counted once per request and record, failed requests, distinct schools, the latest action named by the row that is not an echo, the Supervisor (first reporting line to a manager, by name), the Region, open follow-ups; Usage and suggestions (`_judge_usage`, excessive time against the role's median); the order (online first, then name) |
| Filters | Role (shown when both roles are listed), Program Lead (the Leads people are filed under and those listed, by name), Status (`_matches_status`), the search (name, 80 characters) |
| The strip | `_kpi_items` through the metric registry and `components/context_metrics.html`: the line under a figure cut to its figure and the sentence kept as the note, a tone only where a line is shown |
| The table | `_groups` (each Lead's team under the Lead, then CCEOs without a Lead, then by role), as the feed reads it: the first group of the page (the feed reads one `tbody`); the group head's counts; each row's 16 cells and its Follow up menu item for the Country Director |
| Team Insights | `_insights`: live status shares, active time by module (top five, then Other; ties in the order the rows were read), active staff a day for the seven days to the period's last elapsed day, sign-ins by device |
| The header | Follow-up Queue (with the reader's open follow-ups counted) for the Country Director only |

Every vocabulary comes from `internal/staffactivity/rules.json`, written by
`manage.py export_staff_activity_rules` (drift test
`apps/staff_activity/test_staff_activity_rules_export.py`): the doors per
role, the roles, the dashboard hand-off, the role filter labels and titles,
statuses, periods, thresholds and the activity settings, the time zone, the
page size, the 102 meaningful actions with their labels, modules, school and
echo marks, the subjects that name a school, the open follow-up statuses, the
untracked paths, the 144 sidebar labels and the prefix table a page's part is
read from, the feed's query rules, and three renderings of the strip that the
Go strip is tested against. Two local values were lifted to module constants
in `apps/staff_activity/services.py`, nothing they do changed:
`SUPERVISOR_ROLES` (`_supervisor_names`) and `LEAVE_APPROVED` (`_leave_days`).
The public holidays are the Calendar's port (`calendarpage.PublicHolidayDays`,
a new exported wrapper).

### When Go passes the reader on

- **A school named only in an audit row's payload.** The "schools acted on"
  figure reads a hand-over's or withdrawal's school from `audit_log.payload`,
  which the gateway may not read. When any successful school action in the
  period is about a record other than a school or an activity, Go passes the
  reader to the existing application. On the development data this is every
  week, month, quarter and year that holds a partner hand-over
  (`partner.assigned`, 107 rows, 9–12 Nov). **A narrow view** like
  `gateway_read.decision_audit`, showing the meaningful actions' rows with
  `COALESCE(payload->>'school_id', payload->>'schoolId')` and no other
  payload, would let Go answer them; it is the coordinator's to make.
- A year the national holiday calendar does not cover (1998–2102).
- Two Programme Leads of one name (the filter's order, and a person's Lead,
  would follow a set Python does not order).
- More than one page of groups (50).

## 41.2 Proving it is the same

The log changes by the second (status windows, the time since a beat) and
every sign-in writes to it, so the comparison ran on a private copy of the
development database (`edify_gorn_a20_sa`, `pg_dump` of `edify_gorn_dev`),
read by my own Django (8182) and a Go-only gateway (8082): other agents'
sign-ins on `edify_gorn_dev` could not move a figure between the two answers.

`cmd/parity -screen page -path /staff-activity` asks 41 questions of every
account (45 of a country reader, who is also asked each of the four
Programme Leads the filter offers): the log as it opens; each period, an
unknown one and one with a space; days in and out of the period (a weekend, a
day to come, `20261111`, `2026-W46-1`, nonsense, 30 February, Christmas, a
year before the holiday calendar); every role and status; searches; the
table's page; filters together.

All 29 accounts, Go-only gateway, existing feed on my Django:

```
coordinator@edify.org              41 questions, 0 differing

1197 answers compared, 18 differing
```

Every one of the 18 is a question Go passed on, nine for each country reader
(`go error: unavailable` against the feed's answer): the week, month,
quarter and FY (twice) that hold the partner hand-overs, 12 November and its
ISO week form (hand-overs that day), the week of officers with follow-ups,
and 1890. The 27 other accounts (four Leads sent to the dashboard, Impact
Assessment refused, 22 not found) are 0 differing.

A day filed in the private copy (2025-06-10, rows marked `gpsa…`: four
officers' time, one with 2h 30m in Planning against a role median, three
refused requests, a Core visit and its echo, evidence uploaded, sign-ins on
three devices including one from the evening before) and asked six ways
(the day, a search, Follow-up suggested, a role with an unknown Lead, its
week and month) for the Country Director and the Admin: 102 answers, the
same 18 passed on, the 12 new ones none differing. They cover the Other
module bucket, four parts tied on time, the echo named by the plain row,
"· 1 failed" and the suggestions.

Not run: the pass-on answers through a gateway with my Django behind it (the
run was being started when the incident in 41.5 stopped Postgres).

## 41.3 Tests

Unit (`page_test.go`): the strip against the three exported renderings; the
periods and their labels (week across months and years, quarters, FY, ISO
week dates, refused forms); durations and clocks; parts of the platform;
Usage (median, excessive time, low engagement, failures, leave, a day to
come); groups; the dashboard address; initials, slugs; the strip's figures
and half-even shares.

Integration (`internal/integration/staff_activity_test.go`): an officer's day
filed in the test database (a sign-in on a phone, time in two parts, a Core
visit whose echo row is written last, a refused request) read by the Country
Director: logins, first active, active time, "1 · 1 failed", one school, the
action named by the row that is not the echo, the device share; a hand-over
then passes the reader on; a CCEO is not found, Impact Assessment refused, a
Programme Lead sent to the dashboard with the page's query.

## 41.4 What is left

- The narrow audit view above, so weeks with hand-overs are Go's too.
- A person's detail, the export, the follow-up drawers and saves.

## 41.5 Incident during this piece

Restarting my gateway, I stopped processes with
`kill $(lsof -ti tcp:8082 -sTCP:LISTEN -a -i @127.0.0.1)`. `lsof` ORs its two
`-i` filters, so this sent SIGTERM to every process listening on 127.0.0.1,
not only my gateway: Postgres (now in smart shutdown) and other agents' and
the coordinator's gateways and Djangos, and the Expo server on 8082. Use
`lsof -ti tcp:<port> -sTCP:LISTEN` and check the PID's command before killing.
