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
