# 54 — The Next.js web app's Calendar and Work Plan

The web app (`platform/web`) now draws `/calendar` and `/work-plan` from the
gateway's `PageScreenService.GetPage` answers, which Go builds for every staff
reader (Calendar: doc 34, `internal/calendarpage`; Work Plan: doc 35,
`internal/workplan`). No Go, Django, proto, grant or `platform/mobile` change.

## 54.1 What moved

| Page | How it is drawn |
|---|---|
| `/work-plan` | `FeedPage` like Planning and My Plan (doc 39): header, PC workspace strip, PL scope tabs, approval panel, Monthly / Quarterly / FY tabs, filters, Activity Plan Summary tables and grand total, KPI strip, month bands, Detailed Activity Plan with ticks, row Actions, pager and selection bar. Every block kind it answers with was already drawn. |
| `/calendar` | A page of its own (`components/calendar/*`, `lib/calendarPage.ts`): header and Apply for Leave, people strips (a Lead's officers; the Director's teams and, once one is open, its members) with counts and the open tab, Add other event, filters, the event tabs with counts, and the month card: date badge, month and range, ‹ Today ›, Month / Agenda, the Monday-first grid with each day's events (activities link to `/my-plan/<id>`; leave, holidays and organization events are text with their kind under them), today marked, and the page's note. Under lg the phone calendar: the month with a dot on each busy day, the chosen day's events, All month. Agenda: the month's busy days, each with its date. |

### How the calendar is read back

The feed reads the existing calendar page generically, so its answer has no
calendar block: each event tab carries the phone panel and the grid panel,
whose items run in the grid's order (day number, that day's events, next day
number …, then the month's agenda list and the note). A short label ending a
cell arrives joined to the next day's number as one row (`Observance` + `22`,
`Today` + `14`, the `Sun` heading + `1`), so a row whose value is the day
expected next starts that day and its label belongs to the cell before.
After the last day: its events, then the agenda list (the last list of links,
present whenever the month has an event), then the notes. `readMonth` refuses
a panel whose days do not run 1 … the month's last day.

The web always asks Go for the month (`view` stays on the web side): the agenda
answer drops each day's date (the reader skips the `<h3><time>`), and the
template says the agenda is "the same data as the grid". Today is Kampala's day
(`timezone.localdate()`), as the page marks it.

Page words written on the web side (template words, as doc 39 did): the
weekday headings, the event tabs' kinds (`all`, `activity`, `leave`,
`holiday`, `event`), "No events for this date." (the script's words for a
chosen day in a month without events).

## 54.2 Compared with the existing page

Django on 127.0.0.1:8125 and the web app (3094) on a Go-only gateway
(127.0.0.1:8094), both over `edify_gorn_dev`, 1440 px. For each account and
address: the page title; the calendar's days in order, each with its events'
words (title + the line under it); the people tabs with the open one marked;
for the Work Plan, the Detailed Activity Plan's dates in order.
Accounts cceo, cd, pl1, admin, coordinator, cceo1, ia; addresses `/calendar`,
`?month=12&year=2026`, `?month=2&year=2026`, `?month=10&year=2026`,
`?person=<Paul N.>`, `/work-plan`. Last line as printed:

    42 compared, 0 differing

Screenshots at 1440 and 390 (scratchpad `agent41_{django,next}_*`): cceo
(calendar, work plan, December agenda), cd (own, a member's calendar), pl1,
coordinator. The phone day picker was exercised (choose a day, All month).

## 54.3 What is not drawn yet (the answer does not carry it)

- **Event colours and the legend.** The page colours events by kind
  (`calendar-event--<kind>`); the feed reads no kind, so every event is one
  tone and the legend is left out.
- **Event tabs other than All events.** The page filters them in the browser
  by that kind; the answer carries the same unsorted events in every tab. Here
  All events is drawn and the other tabs open the existing page with
  `?event_kind=<kind>` (which it opens on).
- **Tick boxes and the selection bar** (Reschedule / Cancel): the answer has
  the bar but no event carries a pick id (`PageLink` has none), so neither is
  drawn here.
- **A team member's events** (`?person=`) arrive with title and place joined
  ("Donor VisitKimenyedde …"; the feed joins `<strong>` and `<small>` when the
  event is not a link), and are drawn joined.
- **Multi-day bars and day-off marks** (dashed edge, red day): not in the answer.
- Work Plan: tones of the cost-setup line and of "0 completed / 1 at risk",
  the header button's primary fill and its icon, and the summary drawn as one
  card are the generic blocks' (the same gaps doc 39 lists for Planning).
- Drawers (Apply for Leave, Add other event, Add Non-School Activity, row
  Actions) and the export open on the existing web, as on every web page.
- Partners' calendars are not Go's: the "not moved yet" card.

A contract addition (an event kind/tone and pick id on the calendar's links,
or a calendar block) would close the first four; it touches the Go builder,
the Django feed reader and parity, so it is a separate item (BACKLOG
`web-calendar-work-plan-2`).

## 54.4 Checks (as printed)

- `npm run typecheck` exit 0; `npm run lint` exit 0
- `npm test`: `Test Files  18 passed (18)`, `Tests  134 passed (134)`
  (new: `lib/calendarPage.test.ts`, `components/calendar/CalendarBody.test.tsx`)
- `npm run build` (EDIFY_ENV=development): `✓ Compiled successfully`, routes
  `/calendar` and `/work-plan`, exit 0

## 54.5 The month block (web-calendar-work-plan-2)

The gaps of 54.3's first four points came from the contract: the calendar
reached clients only as text segments. The page contract now carries the
month as a block of its own, additive, in both the existing feed and Go.

| Piece | What |
|---|---|
| Contract | `PageBlock.calendar` (18): `PageCalendar` {year, month, today when it falls in the month, `kinds` (each event-type tab's key, label and count as `PageChip`), `kind` (the tab `?event_kind=` opens), `days`}; `PageCalendarDay` {date, today, day_off, events}; `PageCalendarEvent` {kind, family, title, meta, href, pick_id, continued, day_off}. Go, web and app code regenerated (web and app `src/gen` identical) |
| Existing feed | `apps/mobile_feed/calendar_block.py` reads the page's phone month and agenda (`section.calendar-mobile`, the same `partials/calendar/event.html` chips the grid draws): kind and family from the chip's class list in written order, title `<strong>`, meta `<small>`, the chip's link, the tick box's value, `--continued`, `--dayoff`; the tabs' keys from their `setEventFilter('…')`, the open tab from the page's `eventFilter`, the month and today from the phone grid's days. `page_blocks._blocks` puts it right after the event-type segments (both ways a rail is read). No template or view change |
| Go | `calendarpage`: each entry keeps its family (`_calendar_event_family`, exported per activity type as `event_families` in `rules.json`; a type the vocabulary lacks is "activity"), its tick (`pick_id` = the activity, every day of a run), `continued` (a later day of an activity's run or of an organization event, never leave), `day_off`; `month_block.go` builds the block from the same month the segments draw, after the rail |
| Web | `/calendar` draws from the block, not the text: chips coloured by family/kind as `calendar-workspace.css`, the legend, a dotted edge on a run's later days, red chip and red-edged day for work to reschedule, the phone month's dots per kind, the event-type tabs open this page on their kind (`?event_kind=`, the gateway answers it) and draw only that kind, tick boxes on what the reader may move or cancel (ticking one day of a run ticks every day of it) with the page's bar (Reschedule / Cancel open the existing web, as on every page), and a team member's events with title and place apart. The month card's title, range, badge, empty sentence and note are still the grid panel's fields |

Tooltips (`title=` on the existing chip: responsible person and status)
are not carried.

### 54.5.1 Proved

- `cmd/parity -screen page -path /calendar` over a Go-only gateway (8084)
  and the existing feed of this branch (8184), all 29 seed accounts, 20 s
  apart, with the block in both answers. Its last line:

      1961 answers compared, 0 differing

  The comparison sees the block: a gateway built with `continued` inverted
  made `57 answers compared, 52 differing` for the officer
  (`.blocks[2].calendar.days[0].events[0].continued: go true, existing false`).
- Rows the seed lacks (leave approved and pending, organization events over
  a month's turn, recorded holidays, work on a holiday and on leave): the
  golden harness (`internal/calendarpage/testdata/golden.py`) re-run on this
  branch's own test database and
  `TestTheCalendarMatchesTheExistingFeedOverRowsTheSeedLacks`:
  `24 answers of 6 accounts compared, 0 differing`; the golden answers hold
  the block 24 times, with leave, organization events, continued days and
  day-off marks in it.
- Unit tests: `TestTheMonthBlock` (Go: family incl. an unknown type, the
  tick on every day of a run, continued for a run begun last month and an
  organization event's second day, day-off on entry and day, today only in
  the month, tab keys and counts, the open tab);
  `apps/mobile_feed/test_calendar_block.py` (the real agenda and chip
  partials: kind, family, words, link, tick, continued, day-off, today, tabs,
  open tab, no block without the phone month); web `monthOf`, `kindLink`,
  and `CalendarBody` (family colour, tick box, red day, legend, the open
  tab's entries only).
- The web against the existing page in a browser (`$SP/agent50_compare.cjs`:
  every grid day's visible entries as kind~family~title~line~link~tick~
  continued~day-off, the red day cells, the tabs with counts and the open
  one), 1440 px, accounts cceo, cd, pl1, admin, coordinator, cceo1, ia ×
  /calendar, three other months, `?event_kind=holiday` (this month and
  October), `?event_kind=activity`, two `?person=` calendars:
  see 54.5.2 for the line it printed. Ticking one day of the officer's
  three-day run ticked all three and the bar read "1 activities selected";
  Select all ticked all 13 boxes and the bar read "11 activities selected"
  (the existing page's count).

### 54.5.2 Checks (as printed)

- Browser comparison, web (production build, 3084) against the existing
  page (8184): `63 compared, 0 differing`
- Go: `gofmt -l .` empty; `go vet ./...` clean; `go test -race -count=1
  ./...` exit 0; integration `TestTheCalendar…` and
  `TestGatewayRoleCanNeitherWriteNorReadSecrets` PASS
- Django: `manage.py test apps.mobile_feed
  apps.activities.test_calendar_page_rules_export` (own test database):
  `Ran 219 tests`, `OK`; ruff check / format --check / bandit clean
- Web: typecheck and lint exit 0; `Test Files  18 passed (18)`,
  `Tests  131 passed (131)`; `npm run build` `✓ Compiled successfully`
- Grants: none (the block reads nothing new)

### 54.5.3 What is left

- The chip's tooltip (`title=`: responsible person, status, the day-off
  advice) is not in the block.
- Reschedule / Cancel still open the existing web, where the boxes are
  ticked again (every page's bar does this until the drawers move).
- The app (platform/mobile) does not draw the block yet; its generated code
  knows it.
- The month card's title, range, badge and sentences are still the grid
  panel's fields.
