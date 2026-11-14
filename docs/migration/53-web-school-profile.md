# 53. The web's School Profile (Next.js, M15)

The school profile (School 360, `/schools/<School ID or record id>`) in the
Next.js web app, drawn from the gateway's `SchoolProfileService.GetSchoolProfile`
answer, which Go gives for every tab
([13](13-school-profiles.md): Overview, SSA, Participation, Academic,
Stories, Projects, Core School, Details, any year and period). The School
Directory's names already link here. No Django, Go, proto or grant change.

## 53.1 What was built

| Part | Where | What it does |
|---|---|---|
| Route | `src/app/(app)/schools/[id]/page.tsx` | The profile for the id in the address, with the browser's `tab`, `fy` and `period` |
| Page | `src/components/page/ProfilePage.tsx` | Asks the gateway as the reader; a refused or unknown school is the not-found page; a profile Go hands on (acting reader, Participation over 50 rows: 13.4) says "not here yet" and opens the existing web. Header, tab strip, the open tab's blocks, the bar for ticked activities |
| Layout | `src/lib/schoolProfile.ts` `splitRail`, `trailingPanels` | The engine frame (scope line, facts, filters) runs the page's width; the insights rail sits beside the rest from 1024px (sticky) and under it on a phone; the SSA tab's last two cards sit side by side, two to one (templates/pages/schools/detail.html) |
| Tabs | `profileTabs`, `profileYear` | Each tab links `?tab=<key>&fy=<year>` on the profile's path, the year the page shows and never the period (partials/profiles/_tabs.html); drawn with the shared segmented `TabRail` |
| Lists a figure opens | `profileAsk` | A link carrying anything but `tab`/`fy`/`period` (the rail's and matrix's `what=…&key=…` lists) is not part of the profile request; that address opens the existing web |
| Header | `src/components/blocks/PageHeader.tsx` | A header with a back link or badges is a record header: back link, name, School ID, then the badges (with their reasons as titles) and the doors on one wrapping row; Edit Details primary; a refused door greyed with its reason; drawers open on the existing web. Other pages' headers are unchanged |
| New block kinds | `FeedFacts.tsx`, `FeedRail.tsx`, `FeedChart.tsx`, `FeedSegments.tsx`, wired in `FeedBlocks.tsx` | Facts row; insights rail (figure, meters out of 10, note, Needs Attention links); bar charts, two series as a cut-out bar (owner, 2026-10-09: the shorter value inside, the longer's remainder beyond), legend, round ticks, axis title, "View chart data" table; Participation's Planned/Completed switch with counts and caption, each part drawn by `FeedBlocks` (ticks, Actions) |

## 53.2 What renders

Go-only gateway (127.0.0.1:8082), development database, 2026-11-13. cceo,
School 1000: header with Readiness, SSA FY2027: 6.25 (source in its title),
Staff visit scheduled; Edit Details (primary), Schedule, Add to Project,
Close School; Assign to Partner and Enter SSA Score greyed with the rule's
reasons. Overview: facts, filters, three strips, Best Performing and
Struggling, Latest Change Stories, Profile Insights rail. SSA: Intervention
Matrix, the two cut-out/plain charts, the change and history cards.
Participation: the three tables, the Planned 1 / Completed 2 switch with the
tick box and Actions menu, School Visit Feedback. Details: the three
panels. Admin, School 1151 (Core): the Core School tab.

## 53.3 Comparing with the existing page

Headless Chromium, the same seed account on both (Django 127.0.0.1:8182 over
`edify_gorn_dev`, this app on 3082 over the Go-only gateway), 1440px. Per
address: the h1, the profile tab labels, the year/period selects' chosen
values, the table header cells and every visible table row's cells
(`scratchpad/agent40_compare.cjs`). Addresses: Schools 1000, 1151 (Core),
1078 (closed), 1502 (Champion) × open, `ssa`, `activities`, `core`,
`details` for each account below; for cceo also `academic`, `stories`,
`projects`, `fy=2026`, `fy=2026&period=Q1`, `activities` with `M2`, School
1151, and the unknown School 99999.

| Account | Same | Different |
|---|---|---|
| admin, cd, ia, pl1, business-transformation, coordinator, cceo1 | 20 each | 0 |
| cceo | 12 | 1: `/schools/1000?what=visits_overdue`, by design (53.1: opens the existing web) |

Refusals (cceo1 asking for School 1000, which the gateway answers 404; cceo
asking for 99999) are the not-found page on both. The header badges, doors, strips, rail and panels
are not part of this text comparison; they are the gateway's answer, proved
field by field against the existing feed in 13.2, and were checked by eye in
the screenshots (`agent40_{django,next}_cceo_schools_1000_*_{1440,390}.png`,
`agent40_{django,next}_admin_schools_1151_tab_core_{1440,390}.png`).

Seen in the screenshots, left as they are: the strips keep one row with a
swipe hint (shared `FeedStrip`) where the existing page wraps eight figures;
the Details tab's fields sit three a row rather than four; on a phone the
tab strip shows the open tab and More (the shared `TabRail`) where the
existing page scrolls.

## 53.4 Checks

| Check | Result |
|---|---|
| `npm run typecheck` | clean (exit 0) |
| `npm run lint` | clean (exit 0) |
| `npm test` | `Test Files  18 passed (18)`, `Tests  135 passed (135)` |
| `npm run build` (development, gateway 8082, existing web 8182) | `✓ Compiled successfully`, routes include `/schools/[id]` (exit 0) |

New tests: `src/lib/schoolProfile.test.ts` (request, tab links, year,
layout split, axis, cut-out parts, chart values) and
`src/components/page/ProfileBlocks.test.tsx` (facts, rail, chart, segments,
record header, an outside back link refused). `FeedBlocks.test.tsx`'s "kind
it does not draw" now uses chips (charts are drawn).

## 53.5 What is left

- Every door and row action is a drawer, opened on the existing web (some
  write when opened).
- The rail's and matrix's lists (`what=…`) are the existing web's.
- The profile's other links (district, sub-region, cluster pages) open this
  app's "not here yet" page until those profiles move.
