# 34. The Calendar (M4), read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "Activity planning and scheduling". The migration plan's M4
reads My Plan, Work Plan and the calendar. This piece is the Calendar
(`/calendar`): a month of the reader's own work, approved leave, holidays
and organization events, and for a Programme Lead and the Country Director
the calendars of their people on tabs beside it.

| Piece | What moves | State |
|---|---|---|
| 1 | The Calendar for every staff reader: the month as it opens, other months, the agenda view, the filters, the people strips, the day-off notice, the tick boxes' bar | This document |
| — | A partner's calendar (its Today table, who delivers each entry) | Still the existing application's |
| — | Adding an organization event (`/calendar/events`, a POST), Apply for Leave, Reschedule and Cancel | Still the existing application's |

## 34.1 What moved

`PageScreenService.GetPage` (unchanged contract) is answered for the path
`/calendar` by `platform/backend/internal/calendarpage`, for anyone working
in their own role who is not a partner. A partner role, a staff account
signed in as a partner organisation (`Partner.user_id`), the demo partner
bridge, anyone in an acting capacity and every other path are passed to the
existing application as before.

Go builds the blocks the feed reads from `pages/calendar/index.html` and its
partials (`apps.mobile_feed.page_blocks`) straight from the data.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("calendar")` and the feed's `can_open_url`: every role but the Cluster Leader; a `?format=` the feed has no renderer for is not found |
| The month | `?month=`/`?year=` read with Python's `int()`; either not a whole number, a month outside 1–12 or a year outside 2000–2100 opens the month that holds today, today being the local day (Africa/Nairobi, `ClockService.today`) |
| Whose work | The Admin's: everyone's. `?project_scope=special`: the work of the projects the reader may see (every project for a country reader, a coordinator's own, else those covering the reader's schools; `?project=` narrows to one of them), with no people strip. Anyone else: their own plan (`calendar_scope.plan_of` over both ids, `owner_ids`), or a team member's (`?person=`) |
| What is drawn | Work dated in the month by its scheduled instant's local day, else its planned date, or still running into it (`end_date`); cancelled, rejected, awaiting the owner's approval and completed work (`OFFICER_COMPLETED_STATUSES`) left out unless Status is "Cancelled / rejected"; the Activity type and Status filters; each day of a multi-day activity, counted once ("place · 26–28 November 2026", "Day 2 of 3") |
| Leave | Approved leave, and the reader's own request still waiting ("· Awaiting approval"), of the calendar's person (everyone's for the Admin), a day each; "Your leave" or "<name> leave" |
| Holidays | `public_holidays.holidays_between`: the national calendar of the year (exported for every year the page reaches), the days recorded under Holidays & Blackouts (`PublicHoliday`, `CalendarBlock` PUBLIC_HOLIDAY) first, a recorded Eid replacing the expected one within a week, a recorded day taking a public holiday's date; one entry per day and name |
| Organization events | Active `CalendarBlock` ORG_EVENT of the reader's country (any country for the Admin), by start and title, a day each, "Planning blocked" when it has no description |
| Day-off marks | `day_off.day_off_marks`: planned work still waiting for its day on a public holiday or on its responsible person's approved leave; "Reschedule: public holiday · …" on each day, and the notice above the month ("Reschedule 3 activities in November", or "<name> has … to reschedule" on somebody else's calendar) |
| Links | Each activity opens `/my-plan/<id>`; on somebody else's calendar only where `can_view_record` lets the reader open it (a school in their scope, their own or covered work, or a supervisee's work with no school in a cluster they may read) |
| Tick boxes | `group_actions.tickable_ids`, on the reader's own calendar only: live work they hold (responsible or monitoring) that `_may_run` lets them run, for a role that has My Plan; any tick puts "Select all" in the month and the bar (Reschedule, Cancel) under it |
| People strips | `calendar_people`: a Programme Lead's CCEOs (`team_members`: live CCEO supervisees, a covered Lead's included, by name); the Country Director's teams (`monitor_roster` over `country_oversight.rules.roster`, each Lead first, "No Programme Lead" last, the Director left out), the opened team's people on a second strip; each tab with the number its calendar draws, every link keeping the month and filters, the person last |
| Header and composer | Apply for Leave where the reader may open their leave page and the calendar is their own; Add other event for the Country Director, Admin and Impact Assessment on their own calendar |
| Workspace strip | The Project Coordinator's My Plan / Calendar strip (`build_workspace`) |

How the feed reads the page decides most of the answer and is not obvious:
the five event-type tabs (All events, Activities, Leave, Holidays, Other
events) control one part, so each tab holds the same two panels, the phone's
month and the month itself; the tab label and its count run together
("Activities11"); every loose line, link and heading of a panel is an item
in page order, a line with a letter followed by a figure is paired into a
data row ("Today" over the next day's number, "Planning blocked" over it, or
"Sun" over the 1st), and a link joins the list just before it; an agenda day
is one link, the day's first link (a chip with a tick box always holds one,
even with no address), or, with none, the whole day's words ("Friday 9
October Independence DayPublic holiday"); the day-off notice's own list sits
inside its heading's part and is not read.

The vocabularies are exported, not restated: `manage.py
export_calendar_page_rules` writes `internal/calendarpage/rules.json` (each
role's doors and strip computed through the page's own gates, the activity
types, the status families and options, the hidden and completed statuses,
the work a day-off mark is put on, the untickable statuses, the people
strips' names, the national holiday calendar of 1998–2102 as the existing
code works it out, the recorded-Eid spellings and reach, the time zone, the
settings the page reads and the keys the feed never passes);
`apps/activities/test_calendar_page_rules_export.py` fails when the two
differ. Five values that were literals inside `calendar_view` (the hidden
statuses, the event kinds, the year range, the weekday labels, the
composer's roles) and the two Eid spellings inside `public_holidays._eid_named`
are now module constants there; nothing they decide changed.

## 34.2 Proving it is the same

`cmd/parity -screen page -path /calendar` (`cmd/parity/page_calendar.go`)
asks the Go-only gateway (port 8094, no existing application behind it) and
the existing feed the same questions: the month as it opens; twelve other
months (the year's turn, the FY's, Eid and Easter months, the range's ends);
months and years out of range, padded, signed, with underscores or not
numbers; the agenda view; activity types, statuses and event kinds, known
and not; filters together; the special-projects lens; a person not on the
strip; `?format=`; and, for a reader with a strip, every calendar on it and
on the teams it opens, as it opens, in two other months, filtered, in the
agenda view and with the person padded.

All 29 seed accounts, 20 seconds apart: 1,961 answers (57 for each of 24
accounts, 92 for each Programme Lead, 225 for the Country Director), none
differing. Its last line:

    1961 answers compared, 0 differing

That run's gateway was built before one behaviour-neutral refactor (the
holiday merge moved into its own function for a unit test); after it the
officer, a Lead, the Director and the Project Coordinator were asked again:

    431 answers compared, 0 differing

The seed's November holds the officer's eleven activities (one over three
days, one partner-delivered, tick boxes on all of them), other months hold
the national holidays and observances, and the Lead's and Director's strips
reach every CCEO's calendar.

**Against the existing feed, for rows the seed does not hold.** The seed has
no leave, no organization event, no recorded holiday and no work on a day
off. `internal/calendarpage/testdata/golden.py` files 36 rows in
`edify_gorn_test` (ids `gcal…`): leave approved, pending, rejected, over the
year's turn, with a cover and with a date that is not one; organization
events of the country, of another one, inactive and over the month's turn;
a recorded holiday, one on Christmas Day and an announced "Idd el Fitri";
and the officer's and a teammate's work on those days, over the month's
turn, dated at local midnight (21:00 UTC the day before), programme events
with a district, a venue and neither, a name with stray spaces,
partner-delivered work, work ending before it starts, and work at a school
and in a cluster outside the Programme Lead's reach. It asks the feed 24
questions as six accounts (the officer, an officer with nothing, the Lead on
each calendar, the Director, the Admin, Impact Assessment), writes the rows
and the answers to a file and deletes the rows.
`TestTheCalendarMatchesTheExistingFeedOverRowsTheSeedLacks`
(`internal/integration/calendar_test.go`) files the same rows, asks Go the
same questions through the gateway and compares each answer whole; it is
skipped unless `EDIFY_CALENDAR_GOLDEN` names a file written the same day. It
printed:

    calendar_test.go:133: 24 answers of 6 accounts compared, 0 differing

Changing one word in Go (the pending leave's "Awaiting approval") made 5 of
them differ.

**Unit tests** (`internal/calendarpage/page_test.go`) hold the rest: the
local day at 21:00 UTC and across the year's and the FY's turn, the month
read from the query, the months' ends, range labels, a recorded Eid and a
recorded day merged with the national calendar, each day-off label and
sentence, a team member's calendar and the tab counts, the Director's two
strips and their links, an agenda day with no link, paired lines, Python's
`title()`, and a national calendar for every year the page reaches.

## 34.3 Grants

Appended to `platform/deploy/db/roles.sql` and applied to `edify_gorn_dev`
and `edify_gorn_test`:

    GRANT SELECT (staff_id, status, type, start_date, end_date, covering_staff_id) ON leave TO edify_gateway_ro;
    GRANT SELECT (title, description, start_date, end_date, block_type, is_active, country) ON calendar_block TO edify_gateway_ro;
    GRANT SELECT (date, name) ON public_holiday TO edify_gateway_ro;

No reason, notes, emergency contact or attachment of a leave.

## 34.4 What is left

- A partner's calendar: the Today table with who delivers each entry and
  Name team member, the delivery contact in each entry, the facilitated
  trainings it opens or not. Passed to the existing application.
- Adding an organization event and every save the page leads to.
- Not proved beyond unit tests and reading: a lead covering another lead
  (`TemporaryCoverageAssignment`), a reader who covers an officer, the
  Country Director with operational planning switched off, a year outside
  the exported holiday calendar (none reachable), a leave date Python's
  `fromisoformat` reads in a form other than YYYY-MM-DD, and Unicode digits
  in `?month=`.
