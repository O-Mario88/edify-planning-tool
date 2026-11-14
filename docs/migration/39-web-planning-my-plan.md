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

- **Contract gaps, Planning** (see 39.6 for what agent 26 closed): the header's Export, Plan Field Event and Recent
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

## 39.6 The coordinator's review, fixed (agent 26, 2026-11-13)

The owner's bar is "the UI looks the same or better". Comparing the two pages
side by side found five things this app drew worse than the existing page.
Three were the answer's fault (the feed reader lost words, so the contract
carried less than the page shows), two were drawing.

| Finding | Cause | Fix |
|---|---|---|
| The Client Schools empty state showed only "School Directory" | The feed reader (`page_blocks._panel_items`) walked element children only: a part whose own words run around its elements ("No schools have been clustered yet." around a block; "…still in the `<a>School Directory</a>` — add them…") lost every word outside an element | `_sentences`: a part with words of its own beside an element that has words is read whole, one text item per run, its links as `textLinks` at their words. Go writes the same (`emptyBlocks`). The other empty state now carries its first line too ("No planning records match your filters.") |
| The workload line: a plain card with the first sentence | The same loss: `<p class="edify-note"><strong>…</strong> Core 0 of 0 · Client 0 of 0. …</p>` kept only the `<strong>` | Read whole with `lead` (the bold opening) and the note's `tone` (info, or warning past the ceiling / Core-only). Go now computes the whole of `staff_plan.own_workload` (`workload.go`: held operating schools by type, counted visits Core/Client, the share-out sentences); the share-out numbers are exported (`counted_visits.core_staff_visits`, `core_partner_visits`, `core_type`, `client_rule_types`, `operating_statuses`). The web draws it as the existing note (tinted, 3px tone edge, bold opening) |
| Filter labels "Fiscal year", "Group schools", … | The reader used the select's accessible name; the page draws a short word beside it | Additive `PageFilter.caption` ("FY", "Group", "Readiness", "Show", "SSA"): the span drawn before the select in its holder, when it differs from the name. The web shows the caption and keeps the name for a screen reader |
| The strip wrapped labels and had no rail | Drawing | `StripRail` (static/js/kpi-strips.js): one row, track and thumb, "1–8 of 10", "Swipe for more →" / "Back to start ←", shown only while the cells overflow; the range is counted in first-cell widths as there |
| No "15 / page" chooser | The answer lacked it | Additive `PagePager.size` (the `per_page` select of `edify-pagination-scope`); the pagination strip of an empty list is now a pager block of its own after the empty card (it was folded into the empty panel as text). The web draws the pager as the foot of the table or empty card before it, as the page does, with the chooser (wider than a phone) |

Also drawn now: filters past the row's last slot fold under "More filters"
(micro-ux.js `filterSlots`: 144px a slot, at least three; a phone keeps three
and "More"), its panel opening below the button, with the count of narrowing
filters inside it; header buttons keep one row on a wide screen.

**Contract change (additive, `page.proto`):** `PageFilter.caption = 5`,
`PagePager.size = 3`, `PagePanelItem.lead = 8`, `PagePanelItem.text_links = 9`.
Go and web contracts regenerated; the app's (`platform/mobile/src/gen`) and
the worker's were not (this piece does not touch platform/mobile): `make
proto` there is still to run.

**What else the reader change moved.** Every Go-served page was read for all
29 seed accounts before and after the reader change (21 addresses each, 667
answers; the script compares JSON). Only Planning (every tab, all 28 readers
who may open it) and the existing My Plan of `cceo@` (its past-due note, now
read whole with its link; that reader's My Plan is not Go's) moved. A first
version also read words beside an icon alone (`Month <svg>`) as a sentence
and moved the Calendar and the Decision Log; the rule now needs an element
with words of its own, and neither moves.

**Parity (Go vs the existing feed, my Django 8185 behind gateway 8085):**
`/planning`, all 29 accounts: 26 in one run ("1282 answers compared, 0
differing") and pl3, pl4 and coordinator again after a database outage cut
the first run ("149 answers compared, 0 differing"); `/my-plan`, all 29
accounts: "1943 answers compared, 0 differing".

**Re-shot** (both apps, 1440 and 390 px, `cceo`, `cceo1`, `admin`, `pl1`;
`/planning`, `?tab=clusters`, `/my-plan`, `/clusters`: 64 screenshots,
`agent26_{django,next}_*.png` in the run's scratch folder). Same text, labels
and order for every pair. Differences left, each with its reason:

- **Sidebar, header buttons on Planning, notification badge:** not in the
  answer. Navigation (`GetNavigation`) is forwarded to the existing
  application, which a Go-only gateway does not have; Planning's header
  buttons sit outside `edify-page-header__controls`, so the reader never
  reads them. These are BACKLOG items `navigation-go` (59) and
  `page-header-actions` (60); not done here.
- **Plan-status and lock pills** (red "Not Planned", the lock): the answer
  carries them as text (39.5).
- **School names** are whole here; the existing table truncates them with an
  ellipsis (kept: better).
- **Clusters page's filter fold:** the existing template authors five filters
  and "More filters"; the answer does not say which are folded, so this app
  folds by width (six and More at 1440). Same filters, same values.
- **The empty card's words** are one weight lighter than the existing page's
  slate-400 semibold (same words, same centring).

## 39.7 What web-fixes-2 closed (agent 54, 2026-11-13)

Three gaps agent 26 left (BACKLOG `web-fixes-2`). Each was the answer's
fault, so each is an additive contract field, read by the feed reader and
built by Go, then drawn by the web.

| Finding | Cause | Fix |
|---|---|---|
| Planning's Visit Plan Status, Training Plan Status and Visit Lock drawn as plain text (no red "Not Planned", no padlock) | The cell's chips (`components/school_planning_badges.html`, `partials/planning/visit_lock_cell.html`) arrived as their words run together | Additive `PageCell.pills` (7): one `PageBadge` a chip, `tone` the page's own `data-planning-tone` (none, planned, awaiting, verified, replan, closed, open), `title` the lock's sentence, `icon` "lock" or "unlock" (new name on `PageBadge.icon`). Reader `page_blocks._planning_pills`; Go `clusterpage.ChipPills` / `LockPills` (new `pills.go`) used by the Planning list and a cluster's schools list. The cell's `text` is unchanged. The web draws them as the existing chips (`blocks/PlanningChips.tsx`, the colours of `static/css/components.css`) |
| Clusters' filter row: the existing page shows five filters and More; this app folded by width (six and More) | The template authors SSA status, Cluster risk and Activity status under its own More filters (`partials/clusters/filters.html`); the answer did not say so | Additive `PageFilter.more` (6), set by the reader for a select inside `[data-edify-filter-more-panel]` and by Go for those three. The web's `foldFilters` (lib/filterSlots.ts) keeps authored filters under More and still moves the row's last fields in front of them when the row is narrow, as micro-ux.js does (three and More on a phone) |
| A cluster card's Next Action drawn red here, blue on the existing page | The card's CSS names a risk colour (`.cluster-card__metadata-action--critical :where(dt, dd)`) but `.school-record-row__metadata dd` (higher specificity) wins, so the page draws it as every plain value; the reader took the class word "critical" as alert | Reader skips `cluster-card__metadata-action*` classes (`records.UNSHOWN_TONE_CLASSES`); Go's Next Action fact has no tone. The web also draws a record card's plain values in the accent blue and its toned ones in `--edify-danger/-warning/-success`, as the existing card does (`recordFactTone`) |

Measured in the browser (Playwright, cceo, first card, before the fix):
the existing page's Next Action value `rgb(7, 57, 98)`, this app's
`rgb(190, 18, 60)`; plain values `rgb(7, 57, 98)` there, `rgb(23, 35, 43)`
here. After: both blue.

**Owner question.** The Next Action risk colour looks intended by the CSS
but has not shown since `e3a4faf90` (2026-08-09). The app now follows what
the page shows (plain). If the owner wants the colour, the fix is the
Django CSS specificity, then the reader and Go follow.

**Parity** (Go-only gateway 127.0.0.1:8094 against Django 127.0.0.1:8125,
all 29 accounts, after the reader change):

- `/planning`: "1605 answers compared, 0 differing"
- `/clusters`: "1044 answers compared, 0 differing"
- `/partials/clusters/{id}/schools`, 22 clusters: "2552 answers compared, 0 differing"

Every answer compared is Go's own (no existing application behind the
gateway). The dev data reaches every tone: cceo's Planning carries none,
open, planned, awaiting, verified, replan and closed (with a sentence) chips.

Re-shot cceo `/planning` and `/clusters` at 1440 and 390
(`agent54_{django,next}_cceo_{planning,clusters}_{1440,390}.png`): the chips
match in colour and padlock; Clusters shows five filters and More at 1440
and three and More at 390 on both.

Not done here: the Country Oversight page hides filters with its own
`x-show` toggle ("More filters"/"Fewer filters"), a different pattern the
reader does not mark; it is not Go's yet (planning-oversight-4).
