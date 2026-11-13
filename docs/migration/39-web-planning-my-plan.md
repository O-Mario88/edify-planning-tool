# 39. The web's Planning and My Plan pages (Next.js, M15)

The second and third pages of the Next.js web app ([28](28-web-foundation.md)):
`/planning` and `/my-plan`, drawn from `PageScreenService.GetPage`, the answer
Go gives for both pages ([24](24-planning-page.md) for every Planning tab,
[25](25-my-plan.md) for the My Plan readers Go serves). It changes no Django
code and no Go code; nothing is cut over.

## 39.1 What was built

| Part | Where | What it does |
|---|---|---|
| Routes | `src/app/(app)/planning/page.tsx`, `src/app/(app)/my-plan/page.tsx` | Each asks `GetPage` with its path and the browser's query (`pageQuery`: one value a key, the first, as `request.GET.get`; empty values dropped, as the gateway drops them; `path` refused; bounded) |
| The page | `src/components/page/FeedPage.tsx` | The header, the blocks in the answer's order, the bar for ticked rows. A refused reader gets the not-found page (the feed's 404); a page Go does not answer for this reader (`Unavailable` from a gateway with nothing behind it) is the foundation's "not moved yet" card, opening the same page of the existing web |
| Blocks | `src/components/page/FeedBlocks.tsx` | `filters` (FilterBar, one row with × on a wide screen), `strip`, `panel`, `linkTabs` (the segment rail and the button beside it), `table`, `record`, `pager`, `section`, `empty`, `scopeLine`. A kind neither page answers with yet (chart, rail, list…) is named "not drawn here yet" rather than dropped |
| Strip | `FeedStrip.tsx` | One card of cells; two a row on a phone, as the existing page. A strip with a line under its title (My Plan's Plan Breakdown by Period) is its own titled card; the others keep their title for screen readers only, as the existing pages draw them |
| Table | `FeedTable.tsx` | Title with its count, the line beside it, columns (numeric right-aligned), rows with tones (done, overdue, day off), cell links, pills, tones, the row's buttons and one Actions menu, tick boxes when the page has a bar, an opener for rows that carry details (facts and the SSA panels), group heading rows (Planning's "By PL & CCEO"), the empty sentence and its way out ("Open Planning →"), the note, the pager. On a phone the table stays a table and scrolls whole, no frozen column |
| Record | `FeedRecord.tsx` | Planning's Clusters tab cards: name linking to the cluster, pills, Actions, facts in one flowing "Label: value" line, as the existing cards |
| Panel | `FeedPanel.tsx` | Headings, text (toned), fields, rows, links, a meter, in the panel's order: the workload line and the empty states arrive as panels |
| Selection bar | `SelectionBar.tsx` | Shows once a row is ticked ("2 schools selected", "1 activities selected") with the page's buttons |
| Links | `src/lib/feedPage.ts` | A bare query ("?tab=core") goes on the page's own path; a web path stays (pages not moved open the "not moved yet" card); anything that leaves the site is refused. A drawer action opens the same page on the existing web with the same query |
| Empty filters | `src/lib/emptyFilter.ts`, `FilterBar.tsx` | The existing web's `hideEmptyFilters` (`static/js/micro-ux.js`): a select with fewer than two options and no value applied is not drawn, its value still sent. Applies to every filter row, School Directory's too, as the existing script does |
| Pager | `blocks/Pager.tsx` | Reads the feed's own "Prev" and "Next" pages; the School Directory's pager is unchanged |
| Tones | `blocks/tones.ts` | The feed's tone words (good, caution, alert, plain, and the badge colour names) drawn as the same five tones |
| Search | `src/lib/pageSearch.ts` | "Search planning schools…" and "Search my plan…" (with its label), from `planning_views.py` and `my_plan_views.py` |
| Shell | `src/app/(app)/layout.tsx` | Navigation is still the existing application's (`GetNavigation` is passed on); a gateway with nothing behind it answers `Unavailable`, and the shell now draws without links instead of failing every page |

No rule is in the browser: who may open a page, which rows, tabs, filters,
figures, tones, actions and pages there are, all arrive in the answer.

## 39.2 What renders

Asked of a Go-only gateway (no existing application behind it) on the
development database, 2026-11-13:

| Reader | Planning (every tab) | My Plan |
|---|---|---|
| Admin, Country Director, Impact Assessment, Project Coordinator | filters, strip, tabs, table with rows (and owner heading rows when grouped), pager; Clusters tab cards; Scheduled tab's List/Calendar panel | tabs with Open Calendar, filters, eight-tile strip, four empty tables with Open Planning, Plan Breakdown |
| Officers and leads with no schools (cceo1–19, pl1–4) | filters (district and staff hidden: one option), strip, workload line, tabs, the empty panel ("School Directory", "Showing 0–0 of 0 schools"); Clusters tab cards for leads | as above, plus Planned and remaining (readiness table, subtitle, note) |
| `cceo@edify.org` (the seed's officer with rows) | everything above, with 75 client, 13 core, 1 partner and 2 scheduled schools, 22 clusters | not moved yet: Go passes this reader to the existing application (25, pieces 3–6) |
| Business Transformation | not found | not found |

## 39.3 Comparing with the existing page

Headless Chromium signed the same seed account into the existing web (this
worktree's Django on 8185, development database) and into this app (on 3085,
asking the Go-only gateway on 8085), opened the same address on both at
1440 pixels, and compared what a person sees: the page title, every visible
filter and its selected value, the tabs, and the School IDs of the rows in
order. Eight accounts, seven addresses each (`/planning`, `?tab=core`,
`?group=owner`, `?tab=partner`, `?tab=scheduled`, `/my-plan`,
`/my-plan?period=week`), 2026-11-13:

| Account | Planning (5 addresses) | My Plan (2) |
|---|---|---|
| admin, cd, ia | title, tabs, rows SAME (15, 13, 15, 1, 2 rows); filters DIFFERENT (below) | title, filters, tabs, readiness rows SAME |
| coordinator | title, tabs, rows SAME (8, 5, 8, 0, 0); filters DIFFERENT (below) | SAME |
| cceo1, pl1 | title, filters, tabs, rows SAME (no rows) | title, filters, tabs, the readiness table's six rows SAME |
| cceo | title, tabs, rows SAME (15, 13, 15, 1, 2); filters DIFFERENT (below) | DIFFERENT: the "not moved yet" card (Go passes this reader) |
| business-transformation | DIFFERENT: the existing web sends the refused reader to their dashboard ("Business Transformation"); this app shows not found, as the gateway answers | the same |

What differs and why:

- **Filters:** where all eight Planning filters have a choice, the existing
  page shows six and folds Support and SSA status under "More filters"; this
  app shows all eight in the row. The six shown are SAME in value. The answer
  does not say which filters fold.
- **cceo's My Plan:** not drawn here (25: pieces 3–6 are still the existing
  application's).
- **A refused reader:** the existing web redirects; the gateway answers not
  found, and this app shows the not-found page.

Screenshots of both pages at 1440 and 390 pixels for `cceo`, `cceo1`,
`admin` and `pl1` (Planning, Planning's Clusters tab, My Plan) were looked
at side by side; header, filter row, strip, workload line, segment rail,
table, cluster cards, empty tables with Open Planning, readiness table and
the breakdown read as the same visual system. Pixels were not compared. The
sidebar is empty here (navigation is not Go's yet). The comparison script is
local (not committed: `agent23_compare_used.cjs` in the run's scratch
folder).

## 39.4 Checks

Run in `platform/web` on 2026-11-13:

| Check | Result |
|---|---|
| `npm run typecheck` | clean (exit 0) |
| `npm run lint` (`--max-warnings 0`) | clean (exit 0) |
| `npm test` | `Test Files  10 passed (10)`, `Tests  78 passed (78)` |
| `npm run build` (`EDIFY_ENV=development`, gateway 8085, existing web 8185) | built; routes include `/planning` and `/my-plan` |

New tests: `src/lib/feedPage.test.ts` (the query read, links resolved and
refused, drawer links, group heading rows, buttons and menu items apart),
`src/lib/emptyFilter.test.ts`, and `src/components/page/FeedBlocks.test.tsx`
(rendering answers shaped as the gateway gives them: block order, the
selected filter, a hidden single-option filter still sent, tabs on the
page's path, the heading row across the table, school names linking to the
profile, tick boxes only with a bar, the feed's Next, Open Calendar beside
the tabs, the readiness table's numeric columns, tones and note, an empty
table's sentence, way out and count, the strip's title rule, a cluster card,
and a kind not drawn yet). `vitest.config.ts` now also runs `*.test.tsx`.

## 39.5 What is left

- **Contract gaps, Planning:** the header's Export, Plan Field Event and Recent
  changes buttons are not in the answer (the existing page draws them); the
  workload line carries only its first sentence ("the rest of the note never
  reaches the app", 24.1); the Visit and Training plan statuses and the visit
  lock arrive as plain text, so their pills' colours (red Not Planned, the
  lock) are not drawn; the filter row shows all eight filters where the
  existing page folds two under More filters (the answer does not say which
  fold); the per-page chooser (15 / page).
- **Contract gaps, My Plan:** the readiness table's muted second part of a
  label ("Schools in training · in-school and group trainings") arrives joined
  to the label; the tables' icons; the red sentence inside the readiness note.
- **My Plan for the readers Go passes** (Programme Leads and CCEOs with rows,
  partners): the gateway has no answer for them without the existing
  application behind it, so the page opens in the existing web until
  pieces 3–6 of 25 move.
- **Drawers and saves:** every Schedule, Assign, Export, bulk action and the
  selection bar's buttons open the existing page; nothing writes from here.
  A drawer is never fetched from this app (some write when opened).
- **Navigation** without the existing application behind the gateway: the
  sidebar and the phone's bottom bar are empty until navigation moves to Go.
- **Not compared:** dark theme, an opened row's details against the existing
  page's, the Actions menus' contents, filters with values chosen.
