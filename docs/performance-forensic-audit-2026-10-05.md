# Performance forensic audit — 2026-10-05

Branch `audit/perf-forensics`, on main `3e558109` (PR #214), committed and
pushed on 6 October and not merged. Sections 1–8 are the investigation, made
before any change, on local copies grown to production volume. Sections 9–10
were added the same day once the owner had signed in to the live site and to
DigitalOcean: what production itself records and the findings only
production could show.
**Sections 11–20 are the final report of the optimisation pass**: what was
changed (§11), the before-and-after scorecard (§12), the database, backend,
front-end, legacy-code, reliability and regression reports (§13–18), the
pass/fail matrix against the brief (§19) and the decisions left to the owner
(§20). After that report the owner asked for three more things — the
restyling still left below 1280 pixels, the private network with a
connection pool and a shared cache, and the open database — which are F19
(§15), the switch and the steps of §14, and §20. Shown those decisions, the
owner gave the word on three of them on 6 October; §21 is what was done.
§22 is the fourth, done the same day: the pinned table column on a desktop
(F20), with main merged into the branch first. Where §22 and an earlier
section disagree about the pinned column, the page-header rule or the
caption rule, §22 is the later state.
Every number is the build's own output or production's own telemetry;
line numbers quoted in §1–10 are those of the first baseline, `e12ce29b`.

## 1. Verdict

Two things are slow, and neither is the size of the database.

- **Opening a page** is slow in the browser. Production's Programme Lead
  dashboard: the server takes 1.0 s, then the browser is blocked for 5.7–6.0 s
  on an M1 laptop (§9).
- **Saving a schedule** is slow on the server. Production, one Sunday
  evening: a reschedule runs 457 statements and takes 2.4 s; a cluster bulk
  schedule runs 990–3,576 statements and takes 5.6–18.9 s (§9, F11).

| Symptom | Root cause (measured) |
|---|---|
| Pages freeze / take many seconds | The browser, not the server. At production data volume the server answers in 0.03–1.4 s; the browser then spends 1–11 s (fast laptop) or 3–48 s (4× slower CPU) on the main thread, **84–89 % of it recalculating styles**. §3 F1 |
| Old UI renders, then the new UI | The server sends the older markup; `static/js/micro-ux.js` restyles it after first paint — 1,159 to 4,486 class additions per page plus filter-row, KPI-strip and table re-layout. §3 F2 |
| Black screen between pages | Every click is a full document load. The new document's first frame is an empty `<body>` in the theme background (near-black `rgb(14,21,28)` in the dark theme) for 60–260 ms before the shell is parsed. §3 F3 |
| Database latency unchanged by a bigger database | The database is idle: 12–15 % CPU on the 2 vCPU node since the upsize (§9). The time is in how it is asked: about 2 ms of transit for every statement because the app reaches it over the public network (F13), 35–170 statements per page and 300–3,576 per scheduling save (F11), two lookups with no index that were 60 % of daytime query time (F12, fixed), and a new TLS connection per request (F6). A bigger node changes none of these. |

Across 24 representative role pages at 16,700 schools: server time to first
byte totals **7.8 s**; browser main-thread time totals **32.8 s** on an M1 Pro
and **93.6 s for eight of them** at 4× CPU slowdown.

## 2. What was measured, and where

| Item | Reality |
|---|---|
| Production access | Sections 1–8: **anonymous only** — `/api/health/live`, `/api/health/ready`, `/login`, `/offline`, `/manifest.webmanifest`, one static file (≈600 GETs). Section 9 onward: the owner's signed-in Programme Lead session (read-only page views, 37 pages × 3) and the DigitalOcean control panel (metrics, runtime log, query statistics; nothing changed there). |
| Local environment | macOS, Apple M1 Pro (8 cores), Python 3.13, Django 5.2.17, PostgreSQL 16.15, no Redis (as production), `DEBUG=False`, hashed + compressed static files (`CompressedManifestStaticFilesStorage`), 30-day immutable cache — the production request path |
| Datasets | Demo seed grown with `scripts/scale_local_dataset.py`: **16,700 schools** / 174,472 SSA scores / 24,281 activities (production-sized), and **50,700 schools** / 528,072 SSA scores / 75,281 activities. 20 CCEO accounts, so ≈800 and ≈2,500 schools per officer |
| Server sweep | `scripts/route_timing_sweep.py`: every argument-free GET route × 15 roles = 8,010 requests at 16,700 schools |
| Load test | `scripts/load_test.py`, gunicorn + 4 `UvicornWorker`, admission guard 10 per worker, 10 → 25 → 50 → 75 → 100 virtual users, 60 s each, 3–12 s think time |
| Browser | Headless Chromium (Playwright 1.62), 1440×900 and 390×844, unthrottled and at 4× CPU slowdown, warm HTTP cache. Main-thread figures are `Performance.getMetrics` and Long Tasks with **no profiler attached** — an attached profiler or CSS rule tracking inflates style time roughly 7×, so those runs were used only for attribution |
| Not done | Real devices; Firefox; Safari beyond three browser specs run in WebKit; a 30 min–2 h soak; fault injection; more than 100 users; any write to, or deployment on, production |

## 3. Findings

Severity: P0 causes a reported symptom on most pages; P1 is a measurable
cost on every page or a configuration defect; P2 is real but smaller or
limited to a few pages.

### F1 — Style recalculation is 84–89 % of page-load time (P0)

**Evidence.** Server and browser cost per page, 16,700 schools, warm cache
(ms). `main` is total main-thread time; `longest` is the longest single
freeze.

| Role | Page | Server TTFB | Main thread | of which style | Recalcs | Longest freeze | Main @ 4× CPU |
|---|---|---:|---:|---:|---:|---:|---:|
| CD | `/strategic-priorities` | 463 | 11,309 | 10,480 | 1,268 | 10,018 | **47,776** (one 42 s freeze) |
| PL | `/dashboard` | 293 | 3,578 | 3,225 | 93 | 488 | **17,207** |
| CD | `/core-schools` | 1,398 | 1,741 | 1,429 | 93 | 449 | — |
| Admin | `/schools` | 715 | 1,720 | 1,335 | 21 | 442 | — |
| PL | `/cluster-oversight/` | 634 | 1,292 | 1,066 | 204 | 541 | 5,638 |
| CCEO | `/dashboard` | 210 | 1,256 | 1,050 | 28 | 269 | 5,892 (phone layout 8,488) |
| PL | `/team-targets` | 341 | 1,253 | 1,063 | 65 | 321 | — |
| CCEO | `/schools` | 294 | 1,113 | 890 | 20 | 431 | 6,346 |
| CD | `/analytics` | 351 | 1,062 | 832 | 41 | 255 | — |
| CD | `/dashboard` | 73 | 1,048 | 793 | 78 | 268 | 4,616 |
| IA | `/ia/dashboard/` | 290 | 948 | 784 | 38 | 233 | — |
| HR | `/dashboard` | 212 | 913 | 732 | 61 | 566 | — |
| CCEO | `/my-plan` | 258 | 750 | 587 | 36 | 190 | 3,249 (phone 5,367) |
| CCEO | `/planning` | 369 | 673 | 505 | 30 | 186 | 2,832 (phone 3,626) |
| 24 pages | total | 7,812 | 32,802 | 27,510 (84 %) | | | |

JavaScript execution itself is 2.7 s of the 32.8 s. The scripts are not
slow; what they make the browser do is.

**Root cause — two factors multiplied.**

1. *Each recalculation is expensive.* A whole-document recalculation on the
   CCEO dashboard (2,609 elements) takes **228 ms**; with no stylesheets it
   takes 2.8 ms. Removing one stylesheet at a time:

   | Stylesheet removed | Recalc time | Saved |
   |---|---:|---:|
   | `build/css/consistency.css` | 66 ms | **162 ms (71 %)** |
   | `build/css/platform.css` | 195 ms | 33 ms |
   | `build/css/components/interactions.css` | 216 ms | 12 ms |
   | each of the other 16 | 221–233 ms | ≤ 7 ms |

   Inside `consistency.css` (537 top-level rules), removing single rules:
   rule #243 saves **39.8 ms**, #246 17.6 ms, #240 8.0 ms, #208 8.0 ms. These
   are the selectors the indexed-CSS build writes as one
   `:is(main, .drawer-surface, …) :is(label, dt, th, input, …, <hundreds of
   classes>)` list — 11,562, 3,104, 7,939 and 34,746 characters each. A
   selector whose right-most part is a list that long cannot be filed under a
   class or tag, so the browser tests it against every element on every
   recalculation (11,956 match attempts for each such rule in one traced
   page load, against 23–428 matches).

2. *There are too many recalculations.* A page load forces 20–204 of them
   (1,268 on Strategic Priorities) because the enhancement scripts alternate
   DOM writes with layout reads:
   - `static/js/date-picker.js` `Field.prototype.fit` (lines 287–317) writes
     a style and reads `offsetWidth` five times per date field. Strategic
     Priorities ships 98 date fields inside 100 dialogs rendered up front
     (6,905 of its 8,145 `<main>` elements are hidden); none is visible at
     load. Attributed share of that page's freeze: 92 %.
   - `static/js/micro-ux.js` (`enhance`, `revealTab`, `planRail`,
     `scrollStateOf`, 58 layout-reading call sites) and
     `static/js/kpi-strips.js` `update` (lines 21–31).
   - `static/js/top-layer.js` `rendered()` (line 400, `checkVisibility()`) is
     usually the first reader after those writes, so it is charged for the
     recalculation they caused. It also walks every rule of every stylesheet
     on every page load (`collect`, line 361).

**Why more database capacity changed nothing:** none of this time is on the
server.

**Recommended fix.** (a) In `scripts/build_indexed_css.cjs`, emit the dominant
rules so the right-most compound is a single class or tag (one rule per key,
specificity preserved) instead of one `:is()` list — a mechanical rewrite of
generated output, not of the design. (b) Make `date-picker.js` fit a field
when it becomes visible or is opened, never at load for a hidden one, and
batch its reads. (c) Batch reads and writes across the enhancers so a page
load resolves style a handful of times. (d) F2's fix removes most of the
writes outright.

**Expected improvement.** (a) alone: about −60 % of every recalculation on
every page (162 + 33 of 228 ms is addressable). (b): Strategic Priorities
from 11.3 s to under 1 s. Together with F2: main-thread time per page down
by roughly 80–90 %. To be re-measured after each step, not assumed.

**Risk.** (a) changes selector text for the whole platform; a specificity
slip would restyle something. Needs before/after screenshots of every page
family in all three themes and at three widths. (b), (c) are contained.

**Regression test.** A browser budget in CI per page family: main-thread
≤ 400 ms and ≤ 12 style recalculations at 16,700 schools, unthrottled; a
whole-document recalculation ≤ 60 ms on the CCEO dashboard; no single long
task over 200 ms.

### F2 — The "old UI" is the server's markup; JavaScript turns it into the new one after paint (P0)

**Evidence.** Filmstrip of a sidebar click to `/planning` (frames
`00047–00049`): the first painted frame has a two-row filter bar with
District and Staff fields and a "CLEAR FILTERS" text link, and a KPI strip
reading "Swipe for more"; ~130 ms later the bar is one row, District and
Staff are gone, Clear is an ×, and the strip reads "1–7 of 10". Layout shift
0.30–0.34.

What scripts change after the HTML has arrived:

| Page | Classes added | Attribute writes | Nodes added / removed | Layout shift |
|---|---:|---:|---:|---:|
| PL `/dashboard` | 4,486 | 447 | 209 / 111 | 0.10 |
| CD `/dashboard` | 2,313 | 1,919 | 662 / 323 | 0.00 |
| CCEO `/dashboard` | 2,164 | 126 | 108 / 53 | 0.02 |
| CCEO `/planning` | 1,411 | 122 | 39 / 23 | 0.30 |
| CCEO `/my-plan` | 1,159 | 125 | 16 / 8 | 0.02 |
| CCEO `/schools` | 616 | 105 | 4 / 7 | 0.00 |

Other shifts measured: PL `/team-targets` 0.40, BT `/loans` 0.22, CD
`/analytics` 0.18, PL `/cluster-oversight/` 0.17, coordinator `/projects`
0.15. The time the page is visibly in the intermediate state: 130–200 ms on
a fast machine, **0.7–1.4 s at 4× CPU**.

**Root cause.** `micro-ux.js` is loaded with `defer` and runs
`enhance(document)` on `DOMContentLoaded` (line 2625), after the browser has
already painted (first paint 272 ms, `DOMContentLoaded` 388 ms on
`/planning`). `enhanceStructuralMarkers` stamps the classes the current
design is written against (`edify-cell`, `edify-cell-text`,
`edify-table-plain-content`, `edify-cell-pill`, `edify-head-row*`);
`hideEmptyFilters` (2246) hides selects with fewer than two options;
`arrangeFilterRows` (2329) regroups the bar into one row with a More panel;
`compactClearFilters` (2314) replaces "Clear filters" with the ×; a frame
later `fitRails`, `fitTables`, `wrapLongText` re-plan tables. `kpi-strips.js`
re-pages each strip, and Alpine swaps the theme icon. It is not a duplicate
route, a stale bundle, a service-worker cache or a hydration mismatch: the
service worker never stores a page, static names are content-hashed, and
there is one template per route.

**Recommended fix.** Send the final markup from the server: stamp the cell
and head-row classes, the one-row filter structure, the × control and the
empty-filter omission in the templates/components (`data_table`,
`filter_bar`, `page_header` tags already exist), leaving the script to act
only on content it has not seen marked. Not by hiding the first paint.

**Expected improvement.** First paint equals final UI; layout shift ≈ 0;
1,100–4,500 fewer DOM writes per page, which also removes most of F1's
forced recalculations.

**Risk.** Largest change in this list: it touches shared components and the
heuristics recorded as traps (head-row, column planner, cell-hidden marks).
Do it one component at a time behind pixel comparisons.

**Regression test.** Screenshot at first contentful paint must equal the
screenshot 3 s later for every page family (diff ≤ 0.5 %), CLS ≤ 0.02, and
class additions after `DOMContentLoaded` ≤ 50.

### F3 — Blank (black) frame between pages (P0)

**Evidence.** Every sidebar, tab and bottom-nav link is a full document
navigation (`templates/base.html` 200–231 says so by design). The whole
shell — sidebar, top bar, content — is destroyed and rebuilt each time. With
4× CPU the filmstrip shows, after the old page: one full-screen frame of the
body background and nothing else for 122–259 ms (`filmcold_dark_blue_slow4g`
frames `00016`, `00034`: flat `rgb(0,30,58)`), then the top half of the new
page, then the whole page, then the rewritten page (F2). In the dark theme
that frame is `rgb(14,21,28)`. On a fast machine the browser holds the old
page until the new one paints and no blank frame appears, which is why it
does not reproduce on a developer's laptop.

**Root cause.** The new document's first frame is committed as soon as
`<body>` exists, before the shell markup after it (launch-screen partial,
connectivity partial, then the shell) has been parsed. Nothing tells the
browser to wait. `test_full_page_navigation_is_instant_across_the_platform`
records that cross-document View Transitions were removed for producing "a
black close then reopen effect" — the same blank first frame, made longer by
the transition.

The installed-app launch plate (`templates/partials/pwa_launch.html`,
`#0b1a2c`) was checked as a second suspect: in standalone emulation it
correctly stays down on in-app link navigations (same-origin referrer). It
would show on any in-app navigation that arrives without a referrer; none
was found.

**Recommended fix.** Hold the first frame until the shell is parsed
(`<link rel="expect" blocking="render">` on the shell's main landmark), and
set the page background on `<html>` in the existing inline theme script so
no frame can show the browser canvas. No change to the settled UI.

**Expected improvement.** The previous page stays on screen until the next
is drawable; zero blank frames in Chromium. Safari and Firefox get the
background fix only.

**Risk.** Low. A wrong `expect` target would delay first paint until the
whole document is parsed — still correct, slightly later.

**Regression test.** Filmstrip of ten navigations at 4× CPU in each theme:
no frame with luminance standard deviation < 3.

### F4 — Every navigation re-downloads nothing but re-processes everything (P1)

**Evidence.** Per page: 18–19 render-blocking stylesheets, **1.43–1.51 MB**
(205–222 KB gzip), of which **17–31 % is used**; `pages.css` 0–1 %,
`drawers.css` 1 %. Scripts 433–979 KB, 26–46 % executed. 41 KB of chart
configuration is inline in `<head>` on every page (118 KB on the CCEO
dashboard), uncacheable. First paint minus TTFB: 150–250 ms unthrottled,
450–700 ms at 4× CPU. Largest HTML: Admin `/country-map/` 3.6 MB, RVP
`/dashboard` 2.3 MB, `/cluster-oversight/` 1.7 MB, `/ssa/unmatched` 1.45 MB,
`/country-planning-oversight/coverage-export` 1.4 MB (4.2 MB at 50,000
schools).

**Root cause.** A multi-page application with one global stylesheet stack
and one global script stack; page-specific CSS loads on every page.

**Fix / expected / risk.** Move the inline chart system to a cached file;
load `pages.css` and `drawers.css` rules only where used (the pattern
`feature_css` already established for three files). Saves 150–400 ms per
navigation at 4× CPU. Medium risk: cascade order must be preserved.
**Test:** CSS bytes per page family ≤ budget; first paint − TTFB ≤ 300 ms at
4× CPU.

### F5 — Production database sessions run with `jit=on` (P1, configuration)

**Evidence.** `GET https://edifyplanning.app/api/health/ready` →
`{"status": "degraded", "db": "up", "cache": "unshared", "db_jit": "on"}`.
`config/urls.py` reads `current_setting('jit')` on the pooled session.
`config/settings/base.py` 430–441 records why it must be off (a lending KPI:
4,797 ms with JIT, 76 ms without).

**Root cause.** PgBouncer drops the `-c jit=off` startup option, and the
role default in `scripts/configure_runtime_database_role.sql` (line 56) is
not applied on the live runtime role.

**Exposure today.** Measured, not assumed: of 7,569 statements issued by the
152 slowest role/page pairs with cold caches at 16,700 schools, **none** has
a planner cost above `jit_above_cost` (100,000); the highest is 50,303. So
this is not what is slow today. It becomes one as data grows — the local
Postgres build has no JIT, so the cost at 50,000 schools could not be timed.

**Fix.** Apply the role default (`ALTER ROLE … SET jit = off`). Needs
database-console access, which this session does not have. **Risk:** none.
**Test:** readiness reports `"db_jit": "off"`; alert on `status != ok`.

### F6 — A new database connection for every request (P1)

**Evidence.** `DB_CONN_MAX_AGE=0` (`.do/README.md` line 84), so each request
opens a TLS connection to the pool and authenticates. Production, order
randomised, keep-alive, n=30 each: `/api/health/live` (no database) median
200 ms; `/api/health/ready` (connect + 2 trivial queries) median 253 ms —
**40–50 ms** for connection setup and two round trips (an earlier run: 283
vs 323 ms). Locally without TLS: 3.2 ms. The request
timing probe counts only statements, so this time is reported as "app", not
"db".

**Root cause.** Under ASGI each request runs on its own thread, so Django's
per-thread persistent connections cannot be reused; the setting is correct
for that model and the cost is its consequence.

**Fix.** A process-wide pool (`OPTIONS["pool"]`, Django ≥ 5.1 with
`psycopg_pool`, not currently installed), sized to the admission limit per
worker so 4 × 10 stays within the 40-connection PgBouncer pool.
**Expected:** −30 to −50 ms on every request and less TLS/SCRAM work on both
nodes. **Risk:** medium — pool exhaustion must queue behind the existing
admission guard, never beyond the PgBouncer limit; rehearse under the load
test. **Test:** load test at 100 users holds connections ≤ 40 with zero
connection errors; ready − live ≤ 10 ms.

### F7 — Caches are per worker (P1)

**Evidence.** Readiness reports `"cache": "unshared"`. Four workers each keep
a private `LocMemCache` with 15–30 s lifetimes, so a snapshot is rebuilt up
to four times per window and sessions are read from the database on every
request. Cold versus warm statement counts on the same page: CCEO `/todos`
78 vs 2, `/today/panel` 84 vs 12, PL `/dashboard` 90 vs 48.

**Fix.** A shared cache (managed Valkey/Redis; `REDIS_URL` is already
supported). This is a budget decision the deployment notes reserve for the
owner. **Expected:** median statements per page from ~36 under load toward
the warm figure of 10. **Risk:** low. **Test:** readiness `"cache": "up"`.

### F8 — Query volume and whole-table statements (P2)

**Evidence (16,700 schools).** Sweep of 8,010 requests: 2,103 answered
200 and 0 were server errors; the 1,489 full HTML pages among them took
p50 29 ms, p95 447 ms, p99 1,061 ms (18 over 1 s), with p50 10, p90 29,
p99 57 statements, caches warm. Under the load test:
36 statements per request on average, database 57–62 % of request time,
0 lock waits, at most 5 active database sessions at 100 users.

| Finding | Detail |
|---|---|
| One-off, not an N+1 | CD `/core-schools`: 1,284 statements on a first visit, one repeated 453 times. Profiled again: that is the page creating missing Core plans (its bounded self-heal), once. Every later visit is 79–88 statements |
| Officer-scoped reads scan the whole table | CCEO `/my-plan`, `/dashboard`, `/schools`: the officer's 800 schools are fetched by a sequential scan of all 16,700 rows (12–26 ms per statement, several per page) |
| Slowest single statements | `/ssa` 313 ms (scan of all `ssa_score`), `/planning-monitor/` 287 ms, `/strategic-priorities` 282 ms, `/ia/learning/` 264 ms, `/cluster-oversight/` 242 ms, `/projects/my-plan` 223 ms, `/clusters` 207 ms |
| Sequential scans | `school` was scanned in full 9,288 times during the sweep and load test (149 M rows read) |
| Python-bound | `/country-planning-oversight/coverage-export`: 4.6 s with 17 statements and 10 ms of database time |

At 50,700 schools the 148 slowest pairs go from p50 511 ms / p95 1,475 ms /
max 4,717 ms to p50 997 ms / p95 3,748 ms / **max 13,951 ms** — linear in
the estate, so the 50,000-school target needs the estate-wide pages
aggregated or cached rather than recomputed per request.

Checked and clean: every foreign key has an index (0 of all constraints
missing); no lock waits; no statement over the 30 s timeout.

**Fix.** Pre-aggregate the
estate-wide SSA and activity summaries. **Risk:** each needs its figures
compared before and after. **Test:** per-route statement ceilings in
`apps/telemetry/test_route_performance.py`; cohort p95 at 50,700 schools.

### F9 — 190–200 ms of network under every dynamic request (P2, context)

**Evidence.** From the Nairobi edge: a static file from the CDN 28 ms; the
cheapest origin response 190–200 ms. Static assets are edge-cached and
immutable (`cf-cache-status: HIT`). Every page and every HTMX interaction
pays the origin round trip to Frankfurt before any server work. Not a
defect; it sets the floor and is why extra requests per interaction matter.

### F10 — One unexplained 14.9 s stall in production (P2, open)

One anonymous `GET /manifest.webmanifest` took 14,890 ms to first byte at
about 02:40 EAT; the other ≈600 probes were 24–590 ms. Consistent with a
request waiting for a busy worker or an admission slot
(`WEB_QUEUE_TIMEOUT_SECONDS=20`), but not proven. `queue_ms` in
`interaction_event` would show it.

## 4. Capacity under concurrent users (local, M1 Pro)

| Users | Requests/s | p50 ms | p95 ms | p99 ms | 503s | Busy request threads | DB share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1.4 | 269 | 486 | 564 | 0 | 0.3 | 62 % |
| 25 | 3.3 | 213 | 602 | 1,470 | 0 | 0.8 | 57 % |
| 50 | 6.8 | 185 | 777 | 1,057 | 0 | 1.5 | 60 % |
| 75 | 10.0 | 178 | 611 | 1,039 | 0 | 2.0 | 58 % |
| 100 | 13.3 | 180 | 552 | 1,022 | 0 | 2.7 | 61 % |

No errors, no queueing, no lock waits. This machine has eight fast cores;
production has two shared vCPUs for the web tier and two for the database,
so 2.7 busy threads here is more than that tier can supply. The server-side
ceiling in production is therefore lower than this table and could not be
measured without production-shaped hardware. It is a second-order problem
next to F1: a user waits on their own browser long before the server queues.

## 5. Checked and ruled out

| Suspect | Result |
|---|---|
| Memory leak across navigation | 60 full navigations: heap 3.2 MB, 3,418 nodes, 184 listeners on the same page at navigation 10, 20, …, 60 — flat. Each navigation is a new document |
| Memory growth from in-page swaps | 60 swaps on `/schools`: heap 5.2–5.6 MB, listeners 242 — flat |
| Stale bundles / service worker serving old UI | The worker caches only hashed `/static/` files and the offline page; never a rendered page |
| Dead files | 0 unreferenced static JS/CSS; 1 of 856 templates unreferenced (`partials/my_plan/_priority_group.html`, 2 KB). The legacy is active layers, not dead files (F2, F4) |
| Missing indexes | None on foreign keys. 2,900 indexes (151 MB) is on the heavy side for writes; not a read-latency cause |
| Request waterfalls | Page loads issue 0–2 XHRs (PL dashboard: `/planning-monitor/` 698 ms and `/staff-activity` 123 ms); no chains found |
| Server errors | 0 in 8,010 swept requests and 2,085 load-test requests |

## 6. Open items that need the owner

1. **Production per-route timings.** System Health (admin) already holds
   p50/p95, database time, statement count and queue wait per route. A
   signed-in export or screenshot would replace the local server figures in
   §3 F8 and settle F10.
2. **F5** needs the database console (one `ALTER ROLE`).
3. **F7** is a spend decision (managed cache).

## 7. Proposed order of work

1. F1(b) date-picker — one file, removes the 10–48 s freeze.
2. F3 — two lines in `base.html`, removes the blank frame.
3. F1(a) — the build step, −60 % on every recalculation on every page.
4. F2 — server-stamped markup, component by component.
5. F1(c), F4 — batching and per-page CSS.
6. F5, F6, F8, then F7 if approved.

Each step re-measured with the same scripts against the same two databases
before the next begins.

## 8. Reproducing

Databases `edify_perf_scale` (16,700 schools) and `edify_perf_scale50`
(50,700) are local copies made for this audit. Server sweep and cohort:
`scripts/route_timing_sweep.py`, `scripts/route_pair_timing.py`. Load:
`scripts/load_test.py` (set `DATABASE_URL` to the server's database so its
sessions exist there; its process monitor reads `/proc` and reports zeros on
macOS). Browser harnesses written for this audit are in `scratch/`:
`_prof.cjs` (main-thread metrics), `_sheetcost.cjs` and `_rulecost.cjs`
(recalculation cost per stylesheet and per rule), `_filmstrip.cjs`
(navigation frames), `_rewrites.cjs` (post-load DOM writes), `_mem.cjs`,
`_cov.cjs`, `_selstats.cjs`; and, from §9 onward, `_recalcs.cjs` (which
script line forced each recalculation), `_breadth.cjs` and `_selvariants.cjs`
(elements restyled by one insertion, by rule), `_splitexp.cjs` (F16),
`_exp.cjs` (before/after with a static file overridden) and `_dpcheck.cjs`
(the field-by-field date-picker comparison). The final pass added
`_scorecard.cjs` (§12: the served page against the same page with the
changes taken back out), `_oracle.cjs` (computed styles, old stylesheets
against new on the same DOM, with a same-stylesheet control),
`_domdiff.cjs` (the final DOM under two scripts), `_crawl.cjs` (every page
for script errors and the first-frame hold), `_hasone.cjs` and
`_hasgroups.cjs` (which `:has()` rules widen a restyle), `_stacks.cjs` and
`_fits.cjs` (which script forces each style or layout pass, and how often a
page is fitted). They block the service worker, which otherwise hides
navigations from the test tool's request interception.

## 9. Production evidence (added 2026-10-05, owner signed in)

Read-only throughout: page views as the signed-in Programme Lead, and the
DigitalOcean control panel's metrics, runtime log and query statistics.
Nothing was changed on the live site or in DigitalOcean.

### 9.1 Infrastructure is not saturated

DigitalOcean's own series, 10-minute buckets, 30 September–5 October (after
the upsize). Working hours are Monday–Friday 08:00–18:00 EAT.

| Measure | All hours | Working hours | Peak |
|---|---:|---:|---:|
| Web container CPU (2 vCPU) | 4.9 % mean | 8.4 % mean, 17.6 % p90 | 24.4 % |
| Web container memory | 30 % | 31 % | 47 % |
| Requests per second | 0.18 mean | 0.41 mean, 0.91 p90 | 1.33 |
| Request duration p95 (per bucket) | 1.43 s median | 1.78 s median, 3.56 s p90 | 10 s (chart ceiling) |
| Database CPU (2 vCPU) | 12.4 % mean | 14.8 % mean, 19.2 % p90 | 24.2 % |
| Database load average (1 min) | 0.41 | 0.46 | 3.1 |
| Database memory | 49 % | 48 % | 53 % |
| Restarts | 0 | | |

Of 180 working-hour buckets, 74 had a p95 of 2 s or more, 24 of 3 s or more,
5 of 5 s or more. At under one and a half requests a second and a quarter of
either CPU, that is the cost of the requests themselves, not queueing: every
slow request in the log below reports `queue_ms: 0`.

Database CPU is 11.4 % in the small hours with nobody signed in — background
work (scheduler jobs, health probes that each open a connection) is most of
what the database does.

### 9.2 What the application logged as slow

The web service's runtime log, 4 October 21:58 to 5 October 04:33 EAT (a
Sunday evening), release `e12ce29b860f`: 2,605 requests, of which **155** met
the application's own slow-request rule (1.5 s, or 150 statements). 75 took
3 s or more, 21 took 5 s or more, 5 took 10 s or more; the slowest took
18.9 s. Server time only — the browser's work comes after.

| Count | Request | Role | Total, median / max | Statements, median / max |
|---:|---|---|---:|---:|
| 43 | `POST my-plan/<id>/reschedule` | CCEO, PL | 2.4 s / 4.5 s | 457 / 801 |
| 30 | `GET my-plan` | CCEO, PL | 2.9 s / 4.8 s | 68 / 73 |
| 29 | `POST clusters/<id>/bulk-schedule-drawer` | CCEO | 5.6 s / **18.9 s** | 990 / **3,576** |
| 14 | `POST planning/schedule-action` | CCEO | 3.1 s / 4.3 s | 546 / 782 |
| 10 | `POST my-plan/<id>/edit` | CCEO | 3.6 s / 4.4 s | 693 / 916 |
| 5 | `GET country-planning-oversight/` | CD | 3.9 s / 4.4 s | 52 / 57 |
| 4 | `POST my-plan/<id>/cancel` | CCEO | 3.6 s / 4.5 s | 788 / 834 |
| 4 | `POST core-schools/schedule-visit/action` | CCEO | 1.8 s / 2.3 s | 305 / 330 |

One officer's five consecutive bulk saves, 23:15–23:20 EAT: 1,823, 2,100,
2,435, 2,918 and 3,576 statements; 10.1, 10.5, 12.4, 14.2 and 18.9 s. Each
save cost more than the one before.

### 9.3 Server time for a Programme Lead's 37 pages

Each sidebar page fetched three times; median shown, with the first fetch
where a cold cache made it much slower.

| Page | Server median | of which database | Statements | HTML | First fetch |
|---|---:|---:|---:|---:|---:|
| `/my-plan` | 1,621 ms | 910 ms | 71 | 1,038 KB | 1,869 ms |
| `/team-planning-oversight/` | 1,565 ms | 839 ms | 54 | 858 KB | |
| `/partner-oversight/` | 1,535 ms | 1,069 ms | 88 | 175 KB | |
| `/core-schools` | 1,192 ms | 666 ms | 81 | 731 KB | 1,661 ms |
| `/core-schools-oversight/` | 1,119 ms | 516 ms | 57 | 736 KB | |
| `/fund-requests/weekly` | 1,094 ms | 781 ms | **136** | 200 KB | |
| `/planning` | 1,023 ms | 691 ms | 68 | 266 KB | |
| `/work-plan` | 996 ms | 457 ms | 25 | 377 KB | |
| `/cluster-oversight/` | 864 ms | 507 ms | 59 | 405 KB | 1,314 ms |
| `/schools` | 690 ms | 371 ms | 43 | 478 KB | |
| `/dashboard` | 499 ms | 250 ms | 41 | 405 KB | 1,085 ms |
| `/analytics/program-lead` | 299 ms | 125 ms | 15 | 324 KB | **3,280 ms** (170 statements) |
| `/todos` | 76 ms | 6 ms | — | 264 KB | **2,339 ms** (179 statements) |

Across all 37: median 331 ms, p90 1,192 ms; 7 pages at 1 s or more. Network
and CDN added a median of **226 ms** to every fetch. The four smallest pages
(4–8 statements) spent 8–20 ms in the database: about **2 ms for each
statement** before any query work, against 0.1 ms locally.

### 9.4 The browser on the live site

Programme Lead dashboard, visible tab, M1 laptop, 1440 px: server 1,061 ms
(388 app, 673 database, 73 statements); first paint at 1.4 s; then **14 long
tasks totalling 5.7 s**, back to back until 7.4 s after the click (a second
visit: 13 tasks, 6.0 s). Layout shift 0.25. Two follow-up requests the page
makes for itself: `/planning-monitor/` 1.4–1.6 s and `/staff-activity`
0.4–0.5 s.

One whole-document style recalculation on live pages: dashboard 308–322 ms
(3,235 elements), Planning 416 ms, School Directory 616 ms, Clusters 187 ms,
**My Plan 1,026 ms** (8,543 elements: 230 rows, 2,956 cells, 1,220 buttons);
519 ms with `consistency.css` switched off. The local figures in F1 were, if
anything, low.

### 9.5 What the database spends its time on

DigitalOcean's query statistics (the 72 most-called statements: 2,207,091
calls, 1,573 s in all):

| Time | Calls × mean | Statement | Source |
|---:|---|---|---|
| 749 s | 96,877 × 7.7 ms | `SELECT school.id, SIMILARITY(school.name, …) … WHERE district_id = … AND SIMILARITY(name, …) >= …` | `apps/schools/data_quality.py` `detect_duplicate_candidates`: one query per school, nightly at 03:00 (F14) |
| 343 s | 48,177 × 7.1 ms | `SELECT … FROM core_activity_slot JOIN core_plan WHERE core_activity_slot.activity_id = …` | `Activity.save()`, every save (F12) |
| 88 s | 11,516 × 7.6 ms | `SELECT DISTINCT fund_request.id … WHERE fund_request_item.activity_schedule_cost_line_id IN (…)` | `apply_to_activity`, every re-costing (F12) |
| 59 s | 11,867 × 5.0 ms | `SELECT 1 FROM core_activity_slot WHERE activity_id = … LIMIT 1` | package-credit rules (F12) |
| 27 s | 38,594 × 0.7 ms | `SELECT school_id FROM staff_school_assignment WHERE staff_id = …` (670 rows a call) | scope resolution, every request |

Everything else is under 23 s each. Leaving the nightly job aside, the three
statements marked F12 are **490 of the remaining 824 s — 59 %**. The same
table counts 111,743 `set_config` calls, one for every connection opened,
against 70,207 recorded requests.

## 10. Findings from production

### F11 — A scheduling save runs hundreds to thousands of statements (P0)

**Evidence.** §9.2. Reproduced locally on the 16,700-school copy: a bulk
schedule of five schools on an empty day runs **1,075 statements**; a second
cluster on the same day runs **2,028**. Production's median is 990.

**Root cause.** `bulk_schedule_cluster_visits`
(`apps/planning/cluster_bulk_scheduling.py:369–397`) calls the whole
single-visit pipeline once per school, and each call re-costs every visit
already on that day (`daily_visit_batches/services.py`
`_recalculate_and_write_lines` → `_write_day_lines` → `apply_to_activity`).
Five visits added to an empty day are costed 1+2+3+4+5 = **15 times**
(measured: every statement inside `apply_to_activity` appears 15×); five
added to a day that already holds five, 40 times. Each costing is about 32
statements and writes a cost snapshot, an audit entry and a domain event. A
single reschedule does the same for the day it leaves and the day it joins.
In production every one of those statements also pays the 2 ms of F13.

After a successful reschedule the response is
`<script>window.location.reload()</script>`
(`apps/frontend/views/my_plan_views.py:1074`), so the page the officer was
on — usually My Plan, 2.9 s on the server — is fetched and rendered again.

**Recommended fix.** Add the day's visits first, then cost the day once.
**This needs the owner's decision** (§12): the intermediate costings are
never seen by anyone, but each leaves a cost-snapshot version and an audit
entry, so costing once changes how many of those a save records (a visit
would get snapshot 1, not snapshots 1–5).

**Expected improvement.** 15 costings → 5 on an empty day (about −40 % of
the statements), 40 → 10 on a day already holding five (about −60 %).

**Risk.** Money logic. Needs the daily-batch, costing and fund-request suites
green and a before/after comparison of the final cost lines, snapshots,
advances and fund-request lines for the same day.

**Regression test.** Statement ceilings for a five-school bulk schedule on an
empty day and on a day holding five.

### F12 — Two lookups on the save path had no index (P0, fixed — §11)

**Evidence.** §9.5. `core_activity_slot.activity_id` and
`fund_request_item.activity_schedule_cost_line_id` are plain text columns,
not foreign keys, so nothing indexed them (the foreign-key check in F8 could
not see them). `Activity.save()` runs the first on every save
(`apps/activities/models.py:555`); `apply_to_activity` runs the second on
every re-costing (`apps/budget/costing_service.py:1165`); the unique
constraint on the item table leads with `fund_request` and cannot serve it.
Local plans: `Seq Scan on core_activity_slot`, `Seq Scan on
fund_request_item`.

### F13 — About 2 ms of transit for every statement (P1, configuration)

**Evidence.** §9.3: 8–20 ms of database time for 4–8 trivial statements,
where the statements themselves take 0.04–0.2 ms (§9.5). The web service's
`DATABASE_URL` is `${db.DATABASE_URL}` — the public hostname — and the app's
Networking page offers "Connect to a VPC": it is not attached to one. The
database's connection list shows the scheduler arriving from a public
address.

**Cost.** Statements × 2 ms: about 140 ms on a 68-statement page, 0.9 s on a
457-statement reschedule, 2–7 s on a bulk schedule.

**Fix.** Attach the app to the database's VPC and point `DATABASE_URL` at
`${db.DATABASE_PRIVATE_URL}`; the pool overrides keep working (they change
only name and port). A DigitalOcean setting, so the owner's call (§12).
**Risk:** a wrong network setting is an outage; change it in a quiet hour
with the previous value at hand. **Test:** database milliseconds per
statement on the small pages falls below 1.

### F14 — The nightly duplicate scan asks one question per school (P2)

**Evidence.** §9.5: 96,877 calls, 749 s, 48 % of the listed database time.
`detect_duplicate_candidates` loops over every eligible school and runs a
trigram-similarity query for each; `SIMILARITY(name, x) >= t` written as a
function cannot use the trigram index its docstring names, so each call
scores every school in the district. The job runs at 03:00 EAT, so it does
not slow a working day; it is two minutes of database time a night now and
grows with the square of a district's size.

**Fix.** One set-based statement per district using the `%` operator, which
the index serves. Same candidates, same scores. **Test:** the scan's
statement count is independent of the number of schools.

### F15 — One small DOM insertion restyles most of the page (P0)

*Outcome: fixed at 1280 pixels and wider by rewriting one selector; measured
and not fixed below that. See §15. The text below is the finding as first
written.*

**Evidence.** On the Programme Lead dashboard (3,914 elements), appending
one empty `<span>` to a table cell makes the browser recalculate **2,469
elements** (63 % of the page) and costs **161 ms**; adding a class to the
same cell costs 1 ms. Every fragment HTMX swaps in, every table micro-ux
wraps in a scroll region, every date field wrapped and every KPI-strip
control added is such an insertion — which is why a page load contains ten
near-whole-page recalculations (F1) rather than two.

**Root cause.** Counted exactly from the browser's trace, with one rule
removed at a time:

| Rule removed | Elements restyled |
|---|---:|
| none | 2,469 |
| `responsive-system.css`: `.edify-table-scroll-region… > table > tbody > tr > :is(:first-child:not(:has(> :is(input[type="checkbox"], input[type="radio"], .edify-table-choice))), …)` | 1,229 |
| `platform.css`: `::selection { background: var(--edify-accent); color: var(--edify-on-accent) }` | 1,751 |
| `main.css`: `.tabular-nums` with its `@property --tw-numeric-spacing` | 2,343 |

The first puts a `:has()` on the first cell of every row of every scrolling
table. The second is wide only because of its `var()`s: the same rule
written with the two colours as literals restyles 1,751 — exactly what
removing it does — and still paints the same selection. 68 selectors in all
carry `:has()` on an ancestor rather than on the element being styled.

**Recommended fix.** Express the pinned-first-column rule without `:has()`
(the cell that holds a row's checkbox is already marked by
`enhanceTableChoices`), and give the selection rule its colours per theme
without a custom-property lookup. Each to be proven by comparing computed
styles — `::selection` included, in all three themes — on every element
before and after. Not rushed into this pass: the pin rule carries several of
the owner's rulings about frozen columns, and the selection colours are
design tokens that should not be copied by hand.

**Expected improvement.** Insertions restyle hundreds of elements instead of
thousands; the ten near-whole-page recalculations of a dashboard load shrink
accordingly.

**Regression test.** A browser check that appending one node to a table cell
restyles fewer than 300 elements on the dashboard.

### F16 — Splitting the long selector lists: measured, not yet applied

*Outcome: applied in the build and proven on 365 page states. See §15 and
§18. The text below is the finding as first written.*

Rewriting each long `:is()` list in `consistency.css` as one selector per
alternative (same specificity, same declarations) was tried in the page:
whole-document recalculation on the CCEO dashboard fell from 227 ms to
145 ms (−36 %) with identical computed styles, for about 500 KB more
stylesheet text. The single most expensive rule (#243) went from about 30 ms
to nothing. Worth doing in `scripts/build_indexed_css.cjs` after F15, which
is smaller and removes more.

## 11. What was changed

Everything is on branch `audit/perf-forensics` (on main `3e558109`),
committed on 6 October and not merged. Nothing here changed production or
DigitalOcean; what was changed there, and by whom, is in §21.

| # | Change | Files | Finding |
|---|---|---|---|
| 1 | Date fields are measured when they are drawn, the fields of one scan together | `static/js/date-picker.js` | F1(b) |
| 2 | The first frame waits for the whole document | `templates/base.html` (`<link rel="expect" … blocking="render">`) | F3 |
| 3 | The first frame waits for the page's own start-up scripts: the last deferred script holds it, and every page-level deferred script is in the head | `templates/base.html`, `pages/dashboards/pl.html`, `pages/staff_activity/index.html`, `pages/business_transformation/loans.html`, the five Priorities pages, `partials/priorities/_workspace_scripts.html` and the new `_workspace_head_scripts.html` | F2 |
| 4 | The CSS build writes each long `:is()` list out as one selector per alternative | `scripts/split_selector_lists.cjs` (new), `scripts/build_indexed_css.cjs`, `static/build/css/*` (rebuilt) | F16 |
| 5 | The rule that cuts a pinned name asks its question of the name, not of the cell | `static/css/components/responsive-system.css` (one selector) | F15 |
| 6 | A phone's page is fitted once, not twice | `static/js/micro-ux.js` | F17 (new, §15) |
| 6a | Three questions the stylesheets asked of a table, a heading row or a tab rail with `:has()` are answered once and kept on that element as an attribute; four more are asked of the styled element instead | `static/js/micro-ux.js`, `static/css/components/responsive-system.css`, `interactions.css`, `components.css`, `pl-dashboard.css`, `templates/partials/my_plan/filters.html` | F18 (new, §15) — the owner's choice of 5 October, "2" |
| 7 | Index on `core_activity_slot.activity_id` | `apps/core_schools/models.py`, migration `0012` (written as `0011`; §22.5) | F12 |
| 8 | Index on `fund_request_item.activity_schedule_cost_line_id` | `apps/fund_requests/models.py`, migration `0019` | F12 |
| 9 | Pooled sessions run with `jit = off` (a role default in this database; a notice, not a failure, where the role may not set it) | `apps/system_health/migrations/0003_pooled_sessions_jit_off.py` | F5 |
| 10 | Five more rules ask their question of the element they style, count that element's siblings, or read an attribute the shell template writes for the search box; two of them only below 1280 pixels, with the original kept for wider windows | `static/css/platform.css`, `components/interactions.css`, `components.css`, `components/mobile-shell.css`, `templates/layouts/shell.html`, `static/js/micro-ux.js` | F19 (new, §15) — the owner's request of 5 October |
| 11 | A pool of open database connections in each web process, behind a switch that is off (`DB_APP_POOL`); with it on, a request hands its connection back as it leaves the admission guard | `config/settings/base.py`, `prod.py`, `loadtest.py`, `apps/core/concurrency.py`, `apps/core/boot_gates.py`, `config/urls.py`, `requirements/base.txt` (`psycopg-pool`) | F6 — built and rehearsed, not switched on (§14) |
| 12 | The DigitalOcean steps for the private network, the trusted sources, that pool and a shared cache, each with its check and its way back | `.do/README.md` | F13, F6, F7 and the open database — written, not applied (§20) |
| 13 | The pinned table column reads from the cell whether a row starts with a selection box, a fifth fact the shell script keeps; the two rules F19 had split by width are written one way again | `static/js/micro-ux.js`, `static/css/components/responsive-system.css`, `static/css/platform.css` | F20 (new, §22) — the owner's word of 6 October |

No feature, workflow, permission, calculation, query result or label was
changed, and no code was deleted. One thing a person can see did change, as
a consequence of change 3, and is set out in §18: at laptop widths a page
now opens fitted for the width it has, where before it could open fitted for
a narrower one. The owner was shown it and kept it (§20, 3). Tried and
withdrawn because they did
not measure: asking for the typeface early from the head; running the
top-layer's style read once per frame instead of once per change (it is only
the first reader — the same work happens a moment later without it).

## 12. A — System performance scorecard

Before and after are the **same session, the same server and the same
data** (16,700 schools): "after" is the page as the branch serves it;
"before" is that page with the changes taken back out on the way to the
browser (the original stylesheets, date-picker and micro-ux, no `expect`, no
held frame). Medians of five loads (three for the Country Director, Admin
and IA pages, the Programme Lead's phone dashboard and everything at 4×
slowdown), warm cache, headless Chromium, M1 Pro, no profiler attached.
Every table in §12.1–12.3 was measured again on the build as it stands,
after everything in this report, in one session on 6 October.

"Finished" is the time from the request to the last script write or long
task: the page as the user will use it. "Drawn after the first frame" counts
class changes made to the server's own markup after the browser first
showed it — the "old UI, then new UI".

### 12.1 Opening a page — desktop, 1440×900

| Role, page | Main-thread work (ms) | Style recalculation (ms) | Finished (ms) | Longest freeze (ms) | Layout shift | Drawn after the first frame |
|---|---:|---:|---:|---:|---:|---:|
| CCEO `/dashboard` | 1,232 → **628** (−49 %) | 1,028 → 404 | 1,506 → **891** | 261 → 174 | 0.020 → 0 | 1,725 → **0** |
| CCEO `/my-plan` | 769 → **483** (−37 %) | 597 → 287 | 1,051 → **760** | 200 → 123 | 0.016 → 0 | 979 → **0** |
| CCEO `/planning` | 623 → **403** (−35 %) | 459 → 200 | 1,012 → **802** | 182 → 86 | 0.303 → 0 | 1,265 → **0** |
| CCEO `/schools` | 1,098 → **634** (−42 %) | 875 → 396 | 1,431 → **965** | 432 → 212 | 0.002 → 0 | 528 → **0** |
| CCEO `/calendar` | 292 → **195** (−33 %) | 162 → 42 | 402 → **346** | 0 → 0 | 0.001 → 0 | 72 → **0** |
| CCEO `/core-schools` | 271 → **238** (−12 %) | 129 → 68 | 598 → **529** | 0 → 60 | 0 → 0 | 342 → **0** |
| PL `/dashboard` | 3,444 → **1,238** (−64 %) | 3,101 → 872 | 3,789 → **1,548** | 471 → 166 | 0.102 → 0.101 ¹ | 3,316 → 1,417 ¹ |
| PL `/team-planning-oversight/` | 822 → **588** (−28 %) | 622 → 363 | 1,045 → **806** | 196 → 135 | 0.020 → 0 | 1,607 → 43 |
| PL `/work-plan` | 621 → **476** (−23 %) | 444 → 269 | 861 → **722** | 163 → 120 | 0.272 → 0 | 1,475 → 2 |
| CD `/dashboard` | 931 → **540** (−42 %) | 679 → 276 | 1,037 → **644** | 252 → 88 | 0 → 0 | 2,260 → 910 ¹ |
| CD `/analytics` | 1,029 → **508** (−51 %) | 810 → 259 | 1,406 → **886** | 249 → 80 | 0.179 → 0 | 353 → 7 |
| CD `/strategic-priorities` | 10,921 → **861** (−92 %) | 10,164 → 297 | 11,439 → **1,336** | 9,675 → 301 | 0 → 0 | 532 → **0** |
| CD `/country-planning-oversight/` | 1,010 → **544** (−46 %) | 774 → 277 | 1,107 → **644** | 253 → 89 | 0 → 0 | 2,260 → 910 ¹ |
| Admin `/schools` | 1,637 → **816** (−50 %) | 1,299 → 467 | 2,262 → **1,448** | 434 → 218 | 0.002 → 0 | 533 → **0** |
| IA `/ssa` | 2,385 → **691** (−71 %) | 2,099 → 395 | 3,220 → **1,509** | 565 → 144 | 0.049 → 0.001 | 2,902 → 116 |

¹ These pages fetch sections after they are shown (the Programme Lead's
embedded Planning Monitor and Staff Activity, the Country Director's tab
panels). What is drawn after the first frame there is those sections
arriving, which is the page's design and was not changed.

### 12.2 The same on a slow processor (4× slowdown)

| Page | Main-thread work (ms) | Finished (ms) | Longest freeze (ms) |
|---|---:|---:|---:|
| CCEO `/planning` | 2,863 → **1,598** (−44 %) | 3,249 → **1,954** | 742 → 360 |
| CCEO `/dashboard` | 6,346 → **2,599** (−59 %) | 6,660 → **2,893** | 1,088 → 711 |
| PL `/dashboard` | 15,870 → **5,244** (−67 %) | 16,204 → **5,624** | 2,015 → 706 |

Before F18 the same rows read −8 % to −58 % (−91 % on Strategic
Priorities). Of F19's five rules only the search box's is in force at this
width (§15): it is worth 0–3 % here. One element added to a desktop page
now restyles 1–19 % of the page (9–19 % on the field officer's pages),
where it was 43–47 % before F18 and 110–136 % at the start. The two CCEO
rows of the second table were measured a second time: the machine slept
during the first.

### 12.3 A laptop below 1280 CSS pixels, a tablet and a phone

Many staff laptops are in this group: 1366×768 at 125 % scaling is 1,093
pixels wide to a web page.

| Viewport, page | Main-thread work (ms) | Finished (ms) | Longest freeze (ms) | Layout shift |
|---|---:|---:|---:|---:|
| 1100×800, CCEO `/my-plan` | 1,060 → **542** (−49 %) | 1,351 → **816** | 344 → 123 | 0.207 → 0 |
| 1100×800, CCEO `/dashboard` | 1,313 → **721** (−45 %) | 1,586 → **996** | 296 → 170 | 0.195 → 0 |
| Phone 390×844, CCEO `/my-plan` | 1,263 → **525** (−58 %) | 1,551 → **812** | 424 → 140 | 0.003 → 0 |
| Phone, CCEO `/dashboard` | 1,825 → **666** (−64 %) | 2,089 → **917** | 714 → 182 | 0.006 → 0.004 |
| Phone, CCEO `/planning` | 837 → **440** (−47 %) | 1,232 → **833** | 297 → 104 | 0 → 0 |
| Phone, CCEO `/schools` | 978 → **510** (−48 %) | 1,306 → **850** | 274 → 124 | 0.002 → 0 |
| Phone, PL `/dashboard` | 5,488 → **1,191** (−78 %) | 5,828 → **1,635** | 863 → 163 | 0.001 → 0.001 |
| Phone at 4× slowdown, CCEO `/my-plan` | 6,388 → **2,191** (−66 %) | — ⁵ | 1,782 → 580 | 0.376 → 0.003 |
| Phone at 4× slowdown, CCEO `/dashboard` | 9,108 → **3,110** (−66 %) | — ⁵ | 2,981 → 751 | 0.034 → 0.006 |
| Phone at 4× slowdown, PL `/dashboard` | 23,788 → **5,052** (−79 %) | 24,230 → **5,357** | 3,606 → 677 | 0.001 → 0.001 |

⁵ These two rows were measured in a window long enough for the original
page to finish its work, and the page's self-removing scroll hint leaves
inside it: the "last write" is the hint going, not the page finishing. The
work and the freeze are comparable.

These rows are the build as it stands, after both things the owner asked
for following the first report. The same rows read −26 % to −42 % before
F18 and −38 % to −73 % after it. Against the same build without F19,
alternated in one session, F19 is worth 11–21 % of a phone's page at full
speed and 2–10 % at 1100 pixels (§15). "Before" in these rows is the
original in full; earlier versions of this table left the two stylesheets
that pages load unbuilt as changed, which made "before" a little better
than it was on phones. **A slow phone is still not fast**: 2.2 to 3.1
seconds of work to open a field officer's page, 5.1 seconds for the
Programme Lead dashboard (from 23.8), with freezes of 0.6–0.8 seconds
inside. §15 says what is left.

### 12.4 Moving between pages (sidebar clicks, 4× slowdown, fast-4G throttle)

| | Before | After |
|---|---|---|
| Frames showing only the page background | 109–286 ms on 2–3 of 7 navigations in each theme (near-black in the dark theme) | **0 ms on 12 of 12** (dark and light) |
| Different pictures between the click and the finished page (at the film's 720-pixel resolution) | 4–5 (blank, half a page, the plain page, the restyled page, the fitted page) | **1**: the previous page, then the finished page |
| Layout shift | up to 0.43 | **0** on all 12 |

### 12.5 What the first frame costs

Holding the first frame until the page has started up means the previous
page stays on screen longer, and a page opened in a new tab shows its
background longer: on a fast laptop the first frame comes 0.15–0.65 s later
(the CCEO dashboard: 0.34 s → 0.77 s); on a slow phone at 1.6–2.3 s instead
of 0.45–0.6 s.
What used to appear in that time was the unfinished page, which then moved
(layout shift 0.2–0.4) and was redrawn; the finished page arrives sooner
than it did (the "Finished" columns). The largest-contentful-paint number a
monitoring tool reports will therefore read *worse* on some pages while the
page is in fact usable earlier. The earlier, unfinished frame is one
attribute away (`blocking="render"` in `base.html`) and everything else in
this report stands without it; the owner has chosen to keep the held frame
(§20, 3).

The held frame also changes one thing that is seen once the page has
settled, at laptop widths: the layout shift of 0.195 in the two 1100-pixel
rows of §12.3 was the sidebar sliding shut after the page had been drawn,
and the page used to be fitted while it slid. §18 sets out what that looked
like and what it looks like now.

### 12.6 Weights

| | Before | After |
|---|---:|---:|
| Render-blocking CSS, gzipped | 205.8 KB | 246.22 KB |
| The same, uncompressed (built stylesheets) | 1,374 KB | 2,318 KB |
| Shell JavaScript, gzipped | 139.98 KB | 141.31 KB |
| Requests per page, HTML size, images | unchanged | unchanged |

The stylesheet is heavier on purpose (§15, F16): it is downloaded once and
cached for 30 days, and each page load then does a third to a half less
work. The two ceilings in `test_frontend_budgets.py` were raised with the
reason beside each number, as that file requires (the stylesheet's a second
time, by half a kilobyte, for F19: its selectors are longer, and two rules
are written twice, once for each side of 1280 pixels). One more ceiling
moved for the same reason: the count of `!important` declarations in the
source stylesheets (`test_component_adoption`), 3,963 → 3,967, to the count
exactly. Nothing new is outranked — six of them are the caption rule's three
declarations written out for each side of 1280 pixels, because a selector
cannot be given a width without its declarations being repeated. (F20 took
the split out again: that ratchet is back at main's number, and after the
merge with main the stylesheet weighs 246.19 KB and the shell's scripts
145.50 KB under a ceiling of 146 — §22.)

### 12.7 Server and database

| | Before | After |
|---|---|---|
| `core_activity_slot` looked up by `activity_id` (every activity save; 60,044 calls in production's statistics) | sequential scan: 5–7 ms in production, 2.4–3.1 ms locally | index scan: 0.3–1.2 ms locally |
| `fund_request_item` looked up by cost line (11,516 calls) | sequential scan: 7.6 ms in production, 12.9 ms locally at that volume | index scan: 0.6 ms locally |
| Share of daytime query time among production's 72 most-called statements taken by those two | 59 % | removed once migrated |
| JIT for the application's sessions | on (`/api/health/ready` reports `degraded`) | off after migration `system_health/0003`, where the role may set it |
| Page requests: statements, server time | — | **unchanged** (§14) |
| Scheduling saves: statements, server time | reschedule 457 / 2.4 s; cluster bulk 990–3,576 / 5.6–18.9 s (production) | **unchanged** except for the two lookups above (§14) |
| Concurrency, memory, CPU, connections, error rate | §4, §5, §9 | **not re-measured**; nothing that changed runs on the server per request |

## 13. B — Database report

| Query | Problem | Root cause | Change | Before | After | Plan | Integrity |
|---|---|---|---|---|---|---|---|
| `SELECT … FROM core_activity_slot WHERE activity_id = %s` | 343 s + 59 s of total time in production's statistics; runs on every activity save | `activity_id` is a plain character column, not a foreign key, and had no index | `Index(fields=["activity_id"])`, migration `core_schools/0012` (written as `0011`; §22.5) | Seq Scan, 2.4–3.1 ms (local, production-sized) | Index Scan, 0.3–1.2 ms | `Index Cond: ((activity_id)::text = …)` asserted by `test_slot_activity_lookup_index.py` | An index changes no row; the model's uniqueness rules are untouched |
| `SELECT … FROM fund_request_item WHERE activity_schedule_cost_line_id IN (…)` | 88 s of total time; runs when a week's request is regenerated | the same: a plain column with no index | `Index(fields=["activity_schedule_cost_line_id"])`, migration `fund_requests/0019` | Seq Scan, 12.9 ms | Index Scan, 0.6 ms | catalogue test: an index leads with the column | as above |
| Every statement of a pooled session | PostgreSQL plans with JIT for a workload of thousands of 1–5 ms statements | the database default is `jit = on`; `doadmin` is the only role | `ALTER ROLE … IN DATABASE … SET jit = off` in migration `system_health/0003` (tolerates a role that may not) | readiness: `db_jit: on` | `off` for new sessions | — | a planner setting; no data touched |

Measured and **not** changed, each with its reason:

- **Transit, about 2 ms per statement** (F13): the app reaches the database
  over the public network. Moving it to the private network is a
  DigitalOcean change, not a code change; the steps are written out in
  `.do/README.md` (§20).
- **A new connection per request, 40–50 ms** (F6): not changed for a
  deployment as it is configured. The in-process pool now exists behind a
  switch, with its dependency and its rehearsal against PgBouncer's
  transaction mode (§14); turning it on is one environment variable.
- **The nightly duplicate-school scan, 749 s** (F14): one similarity query
  per school. A set-based rewrite orders ties differently, so "the same
  candidates" could not be proven without an owner ruling on ties.
- **Officer-scoped reads that scan `school`** (F8): 12–26 ms each at 16,700
  schools. No index was added: an officer's 800 rows are 5 % of the table,
  where a scan is a reasonable plan, and no candidate index was benchmarked.
  Every index added in this pass has a measurement behind it; this one
  would not have.
- No N+1 was found on a page (the one candidate, CD `/core-schools`, is a
  one-off self-heal — F8). The repetition is on the **save** path (§14).

## 14. C — Backend report

No request handler, service, query or serializer was changed. What the
server does per request is what it did, as it is deployed today. One thing
was added behind a switch that is off, at the owner's request of 5 October.

**F6 — a pool of open connections in each web process (`DB_APP_POOL`).**
Under ASGI every request has a thread of its own, so it opens a TLS
connection to the managed pool and signs in before its first query: 40–50 ms
of every request in production. With the switch on, each process keeps a
bounded set of those connections open (Django's `OPTIONS["pool"]`,
`psycopg_pool`) and lends one to a request while it runs.

- It is honoured only behind `DB_USE_PGBOUNCER`, for the reason a connection
  lifetime is: connections held open against the cluster itself took
  production down on 12 September. Set on a direct connection it is ignored,
  and a boot warning says so. It refuses to boot with a connection lifetime,
  or in a process that has no admission bound.
- It is sized from `WEB_MAX_CONCURRENT_REQUESTS` — ten requests past the
  guard, and two more connections for what the guard exempts (a health
  probe, the realtime handshake). Four processes are 48 client connections
  to the 40-connection transaction pool; at most 40 statements run at once,
  as now.
- **The rehearsal changed the design.** Django gives a request's connection
  back only after the response has been sent, which is after its admission
  slot has been freed: under saturation a new request was let in while the
  last one's connection was still out. A process had all twelve of its
  connections out in 42 of 49 samples, and in four a request was waiting
  for one. A client slow to take its page would have held a
  connection it had finished with. So with the pool on, a request hands its
  connection back as it leaves the guard (everything that touches the
  database for a finished response is inside it; a stream keeps its
  connection). After that: no sample with a request waiting, and never more
  than 11 connections out in a process.
- Readiness reports the pool when it is on (`"db_pool": {"open", "idle",
  "max", "waiting"}`), so switching it on can be seen from outside.

| Rehearsal: local PgBouncer 1.26 in transaction mode (40 server connections), four workers of ten, 700-school seed | Pool off | Pool on |
|---|---:|---:|
| 100 users, 3–12 s between clicks: requests, p50 / p95 | 1,214; 96 / 221 ms | 1,217; 90 / 207 ms |
| 100 users, 0.2–1 s between clicks (workers saturated): requests in 90 s | 5,996 | 6,985 and 6,604 (two runs) |
| … p50 / p95 | 634 / 1,810 ms | 485 / 1,330 and 536 / 1,472 ms |
| Errors, refusals | 0, 0 | 0, 0 |
| PgBouncer: most client connections; clients waiting; longest wait | 53; 0; 0 | 44; 0; 0 |
| Server connections in use at most | 38 | 38 |
| Most connections out in one process; requests waiting for one | — | 11; 0 |

Locally there is no TLS, so the 40–50 ms this is for is not in those
figures; the faster runs with the pool on were made while another job was
using the machine, and are not offered as a measured gain. What the
rehearsal shows is that the pool holds its bounds and loses no request. It
is **not switched on**: that is one environment variable on the web
component (`.do/README.md`, step 3), after a deploy of this build.

The audit's server finding is F11: a scheduling save repeats the whole
single-visit pipeline per school and re-costs the whole day each time.
Production, one evening: reschedule 457 statements / 2.4 s, edit 693 / 3.6 s,
cancel 788 / 3.6 s, cluster bulk schedule 990–3,576 / 5.6–18.9 s. Measured
again here on one reschedule (176 statements on a one-visit day): 113 are
the day being re-priced (`reschedule_within_batch`), 7 + 8 are the week's
fund request being generated twice (once by the batch, once by the
reschedule itself, which is the pass that also empties the week the visit
left), 7 the month's draft.

It was **not** changed, deliberately. Costing a day once per save instead
of once per visit writes fewer cost-snapshot versions and fewer audit
entries for the same final figures, and the brief for this pass rules out
anything that alters the audit trail. That makes it the owner's decision
(§20), and it is where the remaining server time is: an estimated 40–60 %
of the statements of a bulk schedule (five visits are costed fifteen times
today).

## 15. D — Front-end report

**F16 — long selector lists, split at build time (every page, every width).**
`consistency.css` and its siblings are generated: each `[class*="…"]`
pattern becomes `:is(.a, .b, … )` with up to several hundred alternatives,
and a browser cannot file such a rule under a class — it tries the whole
list against every element on every recalculation. The build now writes any
list of six or more alternatives as one selector per alternative, lifting a
lighter alternative to the list's weight with `:where(x):is(*, <weight>)` so
no rule gains or loses precedence. Lists a browser might weigh differently
(`:has()`, `:focus-visible`, `:nth-child(… of …)` inside) are left as
written. Style recalculation falls 49–64 % on the desktop pages of §12.1.

**F15 — one rule made every insertion restyle the page (1280 pixels and up).**
The rule that cuts a pinned name to its measure asked "does this first cell
hold a selection box?" of the cell: `:first-child:not(:has(> box)) > name`.
A browser answers that for every first child on the page that has a first
child of its own, marks each as something whose contents depend on it, and
from then on restyles what is inside them whenever anything is added
beneath. Asked of the name instead — the name is the cell's first child and
is not a box, so "no box among the cell's children" is "no box after the
name": `name:not(:has(~ box))` — it selects the same elements at the same
weight. One element appended to a table cell:

| Page (1440×900) | Elements restyled, before | After |
|---|---:|---:|
| PL dashboard (3,464 elements) | 1,801 | 1,026 |
| CCEO My Plan (1,989) | 2,715 | 870 |
| CCEO dashboard (2,642) | 2,909 | 1,189 |

**F2 — "old UI, then new UI".** Not a stale bundle and not a second
template: the page was drawn from the server's markup, and `micro-ux.js`
gave it the classes and the shape the design is written against a moment
later. The scripts run in the order they always did; the browser now waits
for them before it draws. That needs the document's last deferred script to
be the one that holds the frame, which is why the deferred scripts that sat
in page bodies moved into the head (the same files, in the same order).
`test_design_system_contract` refuses a deferred script in a page body.

**F3 — the blank frame.** `rel="expect"` on the document's last element; the
browser keeps the previous page until the new one is parsed.

**F1(b) — date fields.** Each of 98 hidden date fields was measured the
moment it was built, which made the browser lay out a closed row 98 times.
They are measured together, when drawn.

**F17 — a phone fitted every page twice (new in this pass).** A phone lays a
page out 980 pixels wide until it has read the viewport line in the head,
and reports the width it settled on as a `resize` event with its first
frame. `micro-ux.js` answers every resize by fitting every tab rail and
table again 150 ms later: three of the ten whole-page style and layout
passes of opening My Plan on a phone. When no resize has arrived since the
page was fitted and the viewport is what it was fitted for, nothing is
re-measured now. A rotation, the keyboard, a zoom, a scrollbar appearing —
and a resize that changes nothing but arrives after the page was fitted —
are fitted exactly as before.

**F18 — questions asked of an ancestor, answered for any element beneath
(below 1280 pixels; the owner's choice after the first report).** A browser
keeps one list, for the whole page, of what to restyle under an element
whose `:has()` answer may have changed. A rule that asks a table, a heading
row or a tab rail a question and then styles *any* element beneath it — a
first child, `> *`, `:not(.title)` — makes that list "everything", for every
element any `:has()` rule hangs on. Below 1280 pixels four families of rules
did so, and one element appended to a table cell on a phone's My Plan
restyled 2,201 of its 2,046 elements (some twice).

They were rewritten in two ways, both selecting exactly the elements they
did, at the weight they had:

| Rule | Was | Is |
|---|---|---|
| Which column of a scrolling table stays in view (17 selectors, below 1280 px) | `table:has(> tbody > tr > :first-child > box, …) > … > :first-child` | `table[data-edify-select-column] > … > :first-child` |
| A heading row that reads as one run of text (4, phones) | `.edify-head-row:not(:has(> :is(p, div, ul, dl, form))) > :not(.title)` | `.edify-head-row:where([data-edify-head-run]) > :not(.title)` |
| A tab rail with an action beside it (2, phones) | `[data-edify-tablist]:has(+ a.btn) > *` | `[data-edify-tablist][data-edify-beside-link] > *` |
| A page header's lead (1, phones and tablets) | `header:has(…) > .lead > *` | `header:has(…) > .lead > :where(eyebrow, title, description, [hidden])` — the only children that header can have |
| A rail's last segment (1, every width) | `rail:not(:has(> More)) > last` | `rail > last:not(:is(More ~ *, :has(~ More)))` |
| A filter's label (1, every width) | `div:has(> select) > span` | `div > select ~ span, div > span:has(~ select)` |
| A dashboard control's label (1) | `control:not(:has(> select[name="fy"])) > span` | `control > span:not(:is(select[name="fy"] ~ *, :has(~ select[name="fy"])))` |

The three attributes are the same questions, put with the same selectors,
by `micro-ux.js`: when it first sees the element, and again — in the same
turn, before anything can be drawn — whenever the element's children or
neighbours change. The elements they sit on are ones the script already
marks (a scrolling table's region and its scroll state, the heading row's
class), so nothing is styled later than it was; the one that is in the
server's markup (My Plan's tab rail) carries the attribute in its template
as well. Each selector keeps its weight with `:is(*, …)`, which matches
everything, and each rewritten rule sits inside
`@supports selector(:has(*))`: a browser too old for `:has()` dropped the
rules these replace, and still drops them.

| One element appended to a table cell | Elements restyled, before | After |
|---|---:|---:|
| Phone, CCEO My Plan (2,000 elements) | 2,121 | 506 |
| 1100×800, CCEO My Plan (1,988) | 2,745 | 443 |

**F19 — what was still restyled below 1280 pixels (the owner's request of
5 October: "can you work on these").** After F18 one element added to a page
still restyled a quarter of it on a phone and a fifth at 1100 pixels. The
browser's own record of why (its invalidation tracking) gave the cause in
one line: the single list it keeps for every `:has()` rule on the page named
`div`, `nav`, `svg`, `input`, `select` and anything with a `type` attribute.
Five rules had put those there, each by asking an ancestor and styling
something plain beneath it. Under the nineteen containers of My Plan that
some `:has()` rule hangs on, that list matched 163 divs, 65 icons and 51
buttons.

The first report said of these that none had an exact rewrite. That was
wrong for four of them, and the fifth needed one attribute in one template:

| Rule | Was | Is |
|---|---|---|
| The last child of a block that holds the page's `h1` (2 rules; 56 of the 61 pages) | `main > div > :where(header, div):has(h1) > :where(div, nav):last-child` | **Below 1280 pixels:** `… > :where(div, nav):last-child:is(:has(h1), :is(h1, :has(h1)) ~ *)` — the last child holds the `h1`, or a sibling before it is one or holds one. **From 1280 pixels:** as it was (below) |
| A school row's icons when it has four actions or more (1, phones) | `.actions:has(> :nth-child(4)) > * svg` | `.actions > :where(:first-child:nth-last-child(n+4), :first-child:nth-last-child(n+4) ~ *) svg` — the first child is at least fourth from the end, and the rest follow it |
| A title beside exactly one action (1, phones; 32 pages) | `.edify-head-row--action:has(> :nth-child(2):last-child) > .title` | `… > .title:is(:first-child:nth-last-child(2), :nth-child(2):last-child)` |
| A KPI caption on a surface that has one straight before a paragraph or heading (2 alternatives; it matches on 3 pages) | `.rounded-surface:has(> .caption + :is(p, h3, h4)) > .caption.uppercase` | **Below 1280 pixels:** `.rounded-surface > .caption.uppercase:is(:has(+ :is(p, h3, h4)), :has(~ .caption + :is(p, h3, h4)), .caption:has(+ :is(p, h3, h4)) ~ *)`. **From 1280 pixels:** as it was (below) |
| The search box's field and form (3; every page) | `search:has(.edify-search-submit) input[type="search"]` | `search[data-edify-has-submit] input[type="search"]` |

The first four select the same elements for any page that could be built,
and weigh the same: the count of a parent's children can be read from a
child's own place among them, and "this block holds an `h1`" is a question
its last child can answer about itself and its earlier siblings. The search
box's attribute is written by the one template that writes the box, on the
condition under which it writes the button
(`{% if not topbar_search.hide %}`), and kept true afterwards by
`micro-ux.js` like the other three; because the server writes it, nothing
is styled later than it was in a browser that does not hold the first frame.
The three rules that no longer contain `:has()` sit inside
`@supports selector(:has(*))`, so a browser too old for `:has()` still gets
none of them, as before.

*(The next three paragraphs and their table are how this stood for a day.
F20, §22, removed the cause, and both rules are written one way again.)*

**Two of the five are asked the new way only below 1280 pixels.** All five
went in at every width at first, and the first write-up of F19 gave desktop
figures that had been measured before it. Measured afterwards at 1440×900,
the page-header and caption rewrites made a desktop page slower to open,
not faster (main-thread work in ms, median of five loads, builds alternated
in one session):

| Build | CCEO dashboard | CCEO My Plan | PL dashboard |
|---|---:|---:|---:|
| Without F19 | 634–640 | 490–492 | 1,292–1,304 |
| All five rewritten at every width (as first built) | 812–813 | 532 | 1,643–1,832 |
| … with the page-header rule asked the old way | 717 | 488 | 1,253 |
| **As it stands**: both asked the old way from 1280 pixels, the new way below | **626–634** | **488–491** | **1,244–1,253** |
| Trial, not shipped: all five at every width, one pinned-column selector taken out | 618 | 479 | 1,155 |
| Trial, not shipped: as it stands, the same selector taken out | 635 | 486 | 1,242 |

Both rewrites look at a sibling (`… ~ *`). From 1280 pixels one selector of
the pinned table columns — the name in the cell after a selection box,
`tr > :first-child:has(> box) + * > :first-child:not(…)` — makes the browser
restyle whole neighbouring subtrees whenever the answer of a `:has()` that
looks at siblings may have changed, and the two rewrites put such a question
on 56 pages. The two trial rows are builds made only to test that (they drop
the selector, and the pinned name's width limit with it): without it the new
way is 1–7 % *cheaper* at desktop width as well, so the cost is that
selector and nothing else. Below 1280 pixels it is not in force. Each of the
two rules is therefore written both ways, with the same declarations, under
`@media (min-width: 80rem)` and its exact complement
`@media not all and (min-width: 80rem)`: every width gets one of two
selectors that pick the same elements, and a rule inside a media query that
does not match costs a browser nothing.

The caption rewrite was first taken out altogether, on the evidence of two
field-officer pages where it changed nothing measurable. A sweep of fourteen
pages then showed the Programme Lead's Work Plan restyling 282 elements for
one insertion without it and 55 with it, so it stays below 1280 pixels: 1–3 %
less work to open that page and Team Planning Oversight on a phone, and each
later insertion there costs 3 ms of style work instead of 12.

| One element appended to a table cell | Original | After F18 | As it stands |
|---|---:|---:|---:|
| Phone, CCEO My Plan (2,047 elements) | 2,121 | 512 | **32** |
| Phone, CCEO dashboard (2,615) | — | 489 | **30** |
| 1100×800, CCEO My Plan (2,042) | 2,745 | 407 | **31** |
| 1100×800, CCEO dashboard (2,610) | — | 275 | **47** |
| 1440×900, CCEO My Plan (2,034) | — ⁶ | 446 | 396 |
| 1440×900, CCEO dashboard (2,610) | — ⁶ | 300 | 239 |

⁶ Not measured on these two pages before any change; F15 measured 110–136 %
of a page at this width.

Across fourteen pages of five roles, at phone and at laptop width, the
figure is 18 to 75 elements — 0.3 to 7 % of the page — with one exception,
the Programme Lead dashboard at 1100 pixels: 161 (4 %). At 1440 pixels the
same fourteen pages restyle 24 to 975 elements, 1 to 19 %.

What that is worth when a page opens, the build as it stands against the
same build without F19, alternated in one session: **11–21 % less
main-thread work on a phone** (the CCEO dashboard 747 → 665 ms, My Plan
617 → 523, the Programme Lead dashboard 1,525 → 1,200), **2–10 % at 1100
pixels** (730 → 717, 574 → 544, 1,355 → 1,212) and 0–3 % at 1440 pixels
(637 → 629, 490 → 490, 1,296 → 1,252 — the search box's rule, the only one
of the five in force there), because every late-arriving section, chart and
script write is an insertion. (That comparison was made while the caption
rule was out; back in below 1280 pixels, it takes the 1–3 % further off the
two Programme Lead pages named above and leaves these six rows as they
are.) The one `<span>` itself cost 29 ms of style
work on a phone's My Plan in the page as F18 left it, and 4 ms with these
five rules rewritten in place.

### What is still slow, and why

Measured, understood, and **not changed**:

1. ~~A desktop still restyles 1–19 % of a page per insertion.~~ **Done on
   6 October (F20, §22):** the pinned table column reads from the cell
   whether a row starts with a selection box, and one insertion restyles
   2–4 % of a desktop page, as it does below 1280 pixels. What is left at
   every width is small: the fields of filter forms, the context-metric
   facts and the page header's own parts, 17–102 elements on the pages
   measured.
2. **The page's scripts write, measure, write, measure.** A phone's My Plan
   still has seven whole-page style or layout passes of 80–120 ms each
   (unthrottled): the top-layer's first look before the start-up scripts
   have written, the filter row measuring itself, the tab rails, the scroll
   regions, the wrapped headings. Each is a correct answer to a real
   question; batching the reads ahead of the writes across `micro-ux.js` is
   a refactor of a 2,700-line file with the owner's layout rulings in it.
3. **The Programme Lead dashboard** is still the heaviest page: 1.2 s of
   main-thread work on a fast machine at phone width (from 5.5 s), 5.1 s on
   a slow phone (from 23.8 s).

## 16. E — Legacy code report

Nothing was deleted, so there is no deletion to justify.

The audit looked for the legacy the brief describes and found none of it
dead: 0 unreferenced static JavaScript or CSS files, 1 of 856 templates
unreferenced (`partials/my_plan/_priority_group.html`, 2 KB), no duplicate
route, no second copy of the UI, no stale bundle (static names are content
hashes; the service worker never stores a page). The "old UI" was the
server's own markup before the page's scripts had run (F2) — live code
doing its job late, not old code to remove. The one unreferenced template
was left: proving no dynamic `{% include %}` builds its name was not done,
and the brief's rule is "if uncertain, do not delete".

## 17. F — Reliability report

| Tested | Result |
|---|---|
| 10 → 25 → 50 → 75 → 100 concurrent users, 60 s each, four workers (§4, before the changes) | 0 errors, 0 refusals, p95 486–777 ms, p99 ≤ 1,470 ms, at most 2.7 busy request threads and 5 database sessions |
| 8,010 swept requests across 15 roles | 0 server errors |
| 60 navigations and 60 in-page swaps | heap, node and listener counts flat (§5) |
| Production as it runs (§9) | web ≤ 25 % CPU, database 12–15 % CPU, queue wait 0 on every slow request logged |
| The connection pool behind a local PgBouncer in transaction mode, 100 users at two paces (§14) | 0 errors, 0 refusals, no request waiting for a connection, at most 11 of 12 connections out in a process, PgBouncer's clients never waiting |
| The pool itself, against the test database | a returned connection serves the next request; a request keeps nothing once it has ended; a full pool makes the next request wait its timeout and no longer; a connection the server dropped is replaced before it is lent |

**Not tested**, and reported as not tested: a long soak (30 minutes to 2
hours), more than 100 users, fault injection (a database restart, a
dropped connection, a slow dependency), recovery behaviour, and any load
test on production-shaped hardware — production has two shared vCPUs for
the web tier, this machine eight fast cores, so the table above is an upper
bound on what production does, not a statement about it. The load test of
§4 was not repeated after the front-end changes because none of them runs on
the server per request; that is an argument, not a measurement. The pool's
rehearsal ran on the 700-school seed, not on the 16,700-school copy.

## 18. G — Regression report

**The stylesheets select and compute what they did.** Every computed value
of every element (and `::before`, `::after`, `::selection`) was read with
the old stylesheets, the new ones swapped in on the same page, and read
again:

| Comparison | Page states | Elements | Computed values | Differences |
|---|---:|---:|---:|---:|
| Split lists alone: 61 pages × light theme × 1440 / 820 / 390 wide | 183 | 436,000 | 356 million | 0 ³ |
| … × blue and dark themes, 1440 wide | 122 | 291,204 | 238 million | 0 |
| … 15 pages × blue and dark × 820 / 390 wide | 60 | 175,338 | 144 million | 0 |
| Split lists and the pinned-name rule against the original stylesheets, the same three sets | 365 | 902,224 | 738 million | 0 |
| After F18 (those, and its rules reading their attributes from the page) against the original stylesheets: 61 pages × light theme × 1440 / 1100 / 820 / 390 wide | 244 | 580,634 | 474 million | 0 |
| … 15 pages × blue and dark themes × 1100 / 390 wide | 60 | 174,398 | 143 million | 0 |
| After F19, against the original stylesheets — now including the two that are served unbuilt (`mobile-shell.css`, `pl-dashboard.css`): the same 244 states | 244 | 580,629 | 474 million | 0 |
| … 15 pages × blue and dark themes × 1100 / 390 wide | 60 | 174,398 | 143 million | 0 |
| F19 with all five rules rewritten at every width (its three `:has()`-free rules inside `@supports`): 61 pages × light theme × 1440 / 1100 / 390 wide | 183 | 435,008 | 355 million | 0 |
| **The build as it stands** (two of those rules written both ways, one for each side of 1280 pixels — §15), against the original stylesheets: the same 183 states | 183 | 434,939 | 355 million | **0** |

³ Three states first reported one or two grid properties changing. The same
report appears when the "new" stylesheets are byte-for-byte the old ones: a
grid inside a skipped (`content-visibility`) section reads the tracks a page
script forced during load, and `none` after any stylesheet is replaced. With
a same-stylesheet swap first as a control, all three are identical. A
deliberately wrong build (one weight dropped) is caught: 55 differences on
one page.

**The pinned-name rule** matches exactly the elements its predecessor
matched over 1,026 arrangements of a row's first two cells, and loses and
wins against the same rival rules either side of its weight — in Chromium
and WebKit (`e2e/pinned-name-selector.spec.js`).

**The split** is held by 11 parser-level tests of its arithmetic
(`tests/js/split-selector-lists.test.cjs`) and a browser test of five lists
against ten rival weights, before and after each
(`e2e/split-selector-lists.spec.js`).

**The date fields** are drawn as they were: all 104 on the 61 pages have
the same width and height under the original and the changed date-picker,
at 1440 and at 390 pixels wide, as the page opens and again with every
closed row on the page opened. One thing the script computes does differ:
the `size` attribute of the 98 fields that sit in closed rows on Strategic
Priorities is 13 where it was 10 (and they no longer carry an empty `style`
attribute), because they are measured when they are drawn instead of while
hidden. Those fields take their container's width, so it changes nothing
that is drawn; it is reported because it is a difference.

**The four attributes say what the selectors said.** On each of the 61
pages, at 390, 820, 1100 and 1440 pixels wide, every table, heading row, tab
rail and search box was checked against the `:has()` selector its attribute
replaced, once per animation frame for four seconds from the moment the page
had started up and again when it had settled: 1,576,297 checks, no
disagreement. `e2e/maintained-facts.spec.js` then changes the page under
each of them 26 ways — a row that starts with a box added, removed, the body
replaced, a paragraph added to a heading row, an action placed beside a
rail, something put between them, a search box given its button, the button
taken away, the box put inside another — and they agree after each, in
Chromium and WebKit. The search box's attribute is also the one the server
writes: `test_the_search_box_says_whether_it_holds_its_button` renders the
shell's search box in eight configurations and finds the attribute exactly
where it finds the button.

**Every rewritten selector selects and weighs what it did.**
`e2e/has-rewrites.spec.js` takes every selector that carries one of the
attributes from the stylesheets as shipped, rebuilds the `:has()` selector
it replaced, and adds the nine that now ask the styled element or count
its siblings — 35 pairs. On a page built to put each through both of its
answers (every run of one to three children under a block, a surface and a
school row's actions among them) they select the same elements and give the
same ruling in 842 contests with 421 rival rules of every nearby weight,
winning some and losing some — in Chromium and WebKit. One of F19's rules
has only this behind it: no audited page has a school row with four
actions, so the comparison of computed styles never met it. A second test
holds together the two rules that are written both ways: the new selector
sits under `@media not all and (min-width: 80rem)` and the old one under
`@media (min-width: 80rem)` with the same declarations, neither appears
anywhere else at those widths, and at 320, 1279, 1280, 1281 and 2560
pixels exactly one of the two queries matches and the rule applies — in
both browsers.

**The page ends as it did — except that at laptop widths it is now fitted
for the width it has.** Each page was loaded as the final build serves it,
twice (what differs between two loads anyway), and as the original build
serves it — the original stylesheets, `micro-ux.js`, date-picker and
dashboard stylesheet, no held first frame — and every element's tag,
classes, inline style, state attributes and drawn size compared in document
order (the three new attributes aside):

| Viewport | Pages | Identical | Flagged, each looked at |
|---|---:|---:|---|
| Phone 390×844 | 61 | 56 | 5: a clock on two (and a colleague's presence going idle on one of them), the HR tie order, and Strategic Priorities and IA's SSA page, both below |
| Tablet 820×1180 | 61 | 53 | 8: a clock and a colleague's presence on one, an icon caught mid-animation on two, the HR tie order, counters and the order of one rail's undrawn children on the Programme Lead dashboard (below), and estimated heights on three — Strategic Priorities, IA's SSA page and team targets, below |
| Laptop 1100×800 | 61 | 34 | 27: **17 are the fit described next** — 13 drawn differently, 4 differing only in the width the script recorded. The other 10: clocks and counters on four, an icon mid-animation, the HR tie order, the date-field attributes, IA's SSA page, a scroll hint caught on its way out, and the map's district names caught before they had been placed |
| Desktop 1440×900 | 21 | 19 | 2: an icon caught mid-animation; the HR tie order |

**At laptop widths a page now opens fitted for the width it has.** This is
the one place where what a person sees has changed. It follows from holding
the first frame (change 3), not from the stylesheets or the attributes of
F18.

Between 1,024 and 1,279 pixels the sidebar is served open, 260 pixels wide,
and the shell's script shuts it to its 72-pixel icon rail as the page
starts, sliding over 200 ms. The same happens at any desktop width for
someone who has chosen to keep the sidebar shut. When the original build
drew the page before its scripts had run, the sidebar was seen sliding shut
(the layout shift of 0.195 in §12.3) and the page was fitted while it slid:
filter rows for the column they had with the sidebar still open, 188 pixels
narrower than the one they ended in; tab rails and tables for wherever the
slide had got to a frame later. Nothing fitted them again unless the window
was resized (or, for rails and tables only, a typeface arrived after the
page had started). The final
build never draws the page with the sidebar open, so nothing slides and
everything is fitted once, for the column the page really has.

What that changes at 1100×800, across the 61 pages on the 16,700-school
copy:

- **13 pages open with something drawn differently.** A filter row shows
  one more field before "More filters" (Loans: five fields of 153 pixels
  where there were four of 185). A tab rail shows a tab that was under
  "More" (Core Schools: Intervention Impact Tracker; IA's dashboard:
  Analysis & Learning, on a page that is also 96 pixels shorter). A fitted
  table's columns are spaced for the room the table has (Performance
  Reviews, the partner's Assigned Schools: columns up to about 20 pixels
  wider or narrower). The pages: the CCEO's Core Schools, To-Dos and weekly
  fund requests; the Programme Lead's cluster oversight; the Country
  Director's Core Schools; IA's dashboard and activity closure; the
  accountant's disbursements; HR's performance reviews; the coordinator's
  reports; the partner's schools; Business Transformation's loans; the
  RVP's dashboard.
- **4 more differ only in the width the script recorded** for a filter row
  or a table (Notifications, partner oversight, Projects, project
  monitoring). Nothing drawn differs.
- **The other 44 are fitted as they were.**

Whether the original fitted a page mid-slide depended on whether the
browser happened to draw it before its scripts started. On this machine My
Plan was fitted mid-slide on the 700-school seed (four filter fields where
five fit) and not on the 16,700-school copy. On a real connection, where a
page arrives in pieces and is drawn as it arrives, the mid-slide fit is to
be expected more often; that was not measured on production. The final
build does not depend on it.

Three checks that this is the original's own fit, reached sooner, and not a
new one:

1. **The final build as it opens, against the original after one resize
   event** (which makes `micro-ux.js` fit the page again): 61 pages, 42
   identical in their markup and in the place, size and text of every drawn
   element, and none of the other 19 differs in how it is fitted. They are
   the clocks, counters, animated icon and tie order above; "More" menus the
   original left hidden in three pages after its first fit; an empty `class`
   attribute and a marker class it left the same way; the date-field
   attributes; the map's district names; the estimated heights of sections
   not yet scrolled to (below); and two that did not repeat when run again
   (a table's recorded width, a section fetched after the page is shown).
2. **The original as it opens, against itself after one resize event**:
   drawn differently on those 13 pages.
3. **The final build's own files with only the hold taken out** open as the
   original does at this width (six pages on the seed: identical in
   everything drawn) — so the stylesheets, the three attributes and the
   other script changes play no part in it.

The same holds for someone who keeps the sidebar shut at a desktop width.
With that choice remembered, at 1440×900, on 21 pages: the original and the
final build open differently on seven. Four are drawn differently — the
Country Director's analytics shows seven filter fields and the Decision Log
tab where the original showed six and "More"; partner oversight's table is
fitted to its region where the original left it 176 pixels wider and
scrolling; IA's dashboard; Loans — and three differ only in the width
recorded. The final build as it opens is the original after one resize
event on all 21, apart from the animated icon, the HR tie order, one hidden
"More" menu the original left behind, and the map's district names caught
before they were placed.

It is reported as a difference because it is one: someone at a laptop sees a
field or a tab that used to be under "More", and table columns a few pixels
from where they were. It is what the same page showed after any resize, and
what the owner's rule for filter rows asks for (a slot for every 9rem of
row, 2026-09-27). Taking the hold out would restore the earlier behaviour
in full; asked which they wanted, the owner kept the new fit (§20, 3). In
Firefox and in Safari before 18.2, which do not hold the first frame, pages
still open as they did. `e2e/performance-budgets.spec.js` now
holds the new behaviour: beside a sidebar that shuts itself, what a page
opens with is what fitting it again gives. It fails on the original build
and on the final one without the hold.

Two more differences are real, and are reported rather than argued away:

- **Strategic Priorities** — the date fields' `size` and `style` attributes,
  above. Nothing drawn differs.
- **The scroll length of three pages before their lower sections have been
  scrolled to.** A section the browser may leave undrawn while it is far
  off screen (`content-visibility`) holds its place at an estimate: the
  height it last had when drawn, or the stylesheet's figure if it has never
  been drawn. The original drew some of these once in the unfinished page
  and kept those heights; the final build never draws the unfinished page.
  So the estimates differ, and with them the length of the page as it
  opens:

  | Page, width | Original, as it opens | Final, as it opens | Either, once scrolled through |
  |---|---:|---:|---:|
  | IA's SSA page, phone | 8,251 px | 7,629 px | 8,586 px |
  | IA's SSA page, tablet | 8,491 px | 7,850 px | 7,984 px |
  | IA's SSA page, 1100 px | 7,019 px | 6,658 px | 7,313 px |
  | Strategic Priorities, tablet | 3,830 px | 3,975 px | 4,015 px |
  | Team targets, tablet | 4,359 px | 4,595 px | 4,247 px |

  Neither build is exact before the page has been scrolled, and neither is
  always the closer: the final build on two of these five rows, the
  original on three. (On the SSA page the original holds the matrix 580–622
  pixels too tall, a height from the unfinished page; the final build holds
  it within 33 pixels of its true height, and both hold the sections below
  at the stylesheet's 362.) Nothing that is drawn differs, and the two
  builds are identical once each section has been reached. It is the length
  of the scrollbar, for as long as the lower sections have not been seen.

A tab rail's children are in the server's order when a phone's page has
opened. In the original that depended on timing: where the second fit (F17)
ran after the first, it had moved the tabs after any divider or status
element in the rail (`restoreRail`); where it ran before, it had not. The
elements that moved are not drawn at phone width (a zero-size divider, a
hidden "Updating…" status), so the difference was never visible; the order
is now the same on every page until the window is really resized.

**After F19 the pages were compared again**, the build as it stands
against the original: all 61 on a phone as they open — 48 identical, and
the other 13 the things already listed (the self-removing "Swipe to view
more columns" hint caught a moment apart on eight; a clock, a counter or a
colleague's presence on three; the date-field attributes; the SSA page's
estimated heights); 21 at 1100 pixels against the original after one resize
event — 17 identical, and a hidden "More" menu the original left behind, an
animated icon, the HR tie order and the map's names caught before they were
placed; 21 at 1440 pixels as they open — 19 identical, the icon and the tie
order. Those comparisons were made with all five of F19's rules rewritten
at every width. The build as it stands differs from that one in two rules
of one stylesheet, each now written both ways (§15); what it was given is
the comparison of every computed style above, on the same 183 page states,
and the second test of `e2e/has-rewrites.spec.js`.

Small existing defects found in passing, not caused or fixed by this work:
the HR dashboard's bars come back from the server in a different order from
one request to the next when two roles tie; a resize moves a rail's divider
to its start (the `restoreRail` behaviour above); and at tablet width the
Period rail inside the Programme Lead dashboard's embedded Staff Activity
section settles in one of three states from one load to the next, with the
original script as with the changed one (ten loads of each). Two more
seen in this last pass: on the 16,700-school copy the country map takes
longer to place its district names than the four seconds its script allows
before showing them unplaced — they are placed 6.5 s after the page starts
in the final build and 8–9 s in the original — so the names flash unplaced
in both (for 0.1 s now, 0.3–1.4 s before); and a name wrapper that
`micro-ux.js` creates after its marking pass is not marked as plain cell
content unless the table is fitted afterwards, which changes nothing drawn
but is why 17 such wrappers differ in one class between the two builds on
the partner's Assigned Schools.

**Every audited page, as served by the final build** (61 pages, 15 roles,
at 1440, at 1100 and at 390 pixels wide): no script error, no failed
response, nothing deferred in a page body, the first frame after the
start-up scripts on all 61 at each width; 58 pages with no class change to
the server's own markup after the first frame and 3 with fewer than 100.

**Automated checks run on the tree as it stands** (again on 6 October,
after the last change to the stylesheets): 4,269 Django tests —
the suites the changes touch, `core`, `frontend`, `system_health`,
`core_schools` and `fund_requests`: the settings, the admission guard, the
budgets, the design-system contract, every inventory and every test that
reads a template or a stylesheet. 4,268 passed. The one that did not,
`test_guard_skips_under_test_runner_argv`, reads how the test run was
started and fails under the launcher used here (`python -c`); run the usual
way (`python -m pytest`) its file passes, 11 of 11. (On an earlier build a
wall-clock latency objective failed in a run made while three other jobs
were using the machine and passed on its own: `/todos` p95 279 ms against
800, `/analytics` 402 ms against 1,500, at 15,000 schools. It passed in this
run.) 61 JavaScript unit tests. The browser specs written or changed here —
performance budgets, maintained facts, rewritten selectors, pinned name,
split lists, date-picker — and the existing built-against-source stylesheet
spec, in Chromium; the three selector specs and the maintained-facts spec
in WebKit as well; the performance and maintained-facts specs against the
16,700-school copy and the standard 700-school seed, and the performance
spec against a development-style server. `npm run build:css` reproduces the
built files; `makemigrations --check`; `ruff`. The page, card, KPI,
interaction and traceability inventories were regenerated (one new partial,
line numbers).

**Not run:** the whole Django suite, the whole browser suite, Firefox
(Playwright's does not start on this machine), Safari on a device, and any
real phone. "Features, workflows, permissions, calculations and data
preserved" is therefore supported by: no server code path changed for a
deployment as it is configured (the pool and what goes with it are behind a
switch that is off); the final DOM and the computed styles compared as
above; and the suites listed — not by an end-to-end pass over every
workflow.

**New gates, so the same things cannot come back quietly:**

| Gate | Holds |
|---|---|
| `e2e/performance-budgets.spec.js` — the first frame is the finished page | no class change to the server's markup, and no layout shift, after the first frame (a sliver is allowed: 5 writes, or a tenth of the page's; the names htmx puts on an element while it fetches a section are not counted — §22.4); nothing deferred in a page body; the first frame comes after the start-up scripts |
| … the recorder sets aside a fetch being announced, and nothing else | the control for the count above: an announcement counts 0; a class stamped, a class stamped in the same write as an announcement, and the same classes written again each count 1 |
| … one element added to a table cell does not restyle the page | under 15 % of the page's elements at 1440 pixels, at 1100 pixels and on a phone (2–4 % now, 3–7 % on the 700-school seed; it was 106–137 %). The desktop ceiling was 35 % until F20 |
| `e2e/maintained-facts.spec.js` | each of the five attributes equals the `:has()` selector it replaced after every one of 35 changes to the page, read within the turn of the change (33 changes, read one task later, until §22.4) |
| `e2e/has-rewrites.spec.js` | every rewritten selector in the shipped stylesheets (40 pairs since F20) selects, and weighs, what the selector it replaced did |
| … a page load resolves style a bounded number of times | ceilings per page (Strategic Priorities 480; it was 1,269) |
| … a phone fits a page once, and fits it again when it is turned | exactly one fit on load; a rotation re-fits and no rail overflows |
| … beside a sidebar that shuts itself, a page opens fitted for the width it has | at 1100 pixels, the fields each filter row shows, the tabs each rail keeps and the width each table was fitted for are the same after the page is fitted again |
| `test_design_system_contract` | the `expect` line and its target; the last deferred script holds the frame; no deferred script in a page body; the shell writes the search box's attribute exactly when it writes the button |
| `test_frontend_budgets` | CSS 246.5 KB and shell JavaScript 146 KB gzipped, each with its reason (141.5 KB until main's two new scripts came in with the merge — §22.1) |
| `test_slot_activity_lookup_index`, `test_item_cost_line_lookup_index`, `PooledSessionsJitDefaultTest` | the two indexes and the JIT default |
| `PerProcessPoolTest`, `PooledConnectionsAreLentNotKeptTest`, `PerProcessPoolReadinessTest`, six tests of the admission guard | the pool is off unless asked for, ignored on a direct connection, sized from the admission bound, refuses a lifetime or an unbounded process; a real pool lends, takes back, bounds and replaces; a request returns its connection with its slot, a stream and a surrounding transaction do not |
| `e2e/date-picker.spec.js` | a field in a closed row is not measured until the row opens |

All counts, not timings, so they read the same on a loaded runner. Each was
seen failing on the code as it was.

## 19. H — Pass / fail

Against the brief's own acceptance list. "Pass" means measured and met;
anything not measured is said to be not measured.

| Criterion | Verdict | Basis |
|---|---|---|
| No 20-second navigation remains | **Pass** as measured | Worst desktop page 11.4 s → 1.3 s. The worst page found anywhere — the Programme Lead dashboard on a phone at 4× slowdown — was 24.2 s and is 5.4 s |
| No unexplained UI freeze remains | **Pass as worded; freezes remain** | Every freeze measured is explained (§15). They are shorter, not gone: up to 301 ms on a desktop at full speed (711 ms at 4× slowdown), 0.6–0.75 s on a slow phone (they were 1.8–3.6 s) |
| No old UI renders before the current UI | **Pass** in Chromium (and Safari 18.2+ by the same mechanism, not tested); **unchanged** in Firefox | Across 61 pages at three widths: no class change to the server's own markup after the first frame on 58, fewer than 100 on 3 (it was 500–4,500); layout shift 0. At laptop widths that includes the sidebar, which was drawn open and slid shut on every page. Sections a page fetches later still arrive plain and are restyled within a frame or two |
| No black route transition remains | **Pass** in Chromium | 0 blank frames in 12 of 12 navigations at 4× slowdown, both themes |
| No major unnecessary API requests remain | **Pass** | Page loads issue 0–2 requests beyond the document (§5); none found to remove |
| No N+1 queries remain | **Fixed on a branch, not deployed** | The bulk day repeated its pricing per school (F11). At the owner's word of 6 October it prices the day once: 1,059 → 584 and 1,981 → 766 statements, the same figures (§21.3). No N+1 on page reads |
| No obvious database bottlenecks remain | **Partly** | Two missing indexes fixed. A connection per request (F6) has its fix built and switched off; per-statement transit (F13) has its steps written; both wait on DigitalOcean (§20). The nightly scan (F14) remains |
| No connection leaks remain | **Not found** | At most 5 database sessions at 100 users as deployed. With the pool switched on (rehearsal, §14): never more than 11 of a process's 12 connections out, none kept by a finished request, none waited for |
| No frontend memory leaks remain | **Not found** | 60 navigations and 60 swaps flat. Not a long session |
| No backend memory leaks remain | **Not measured** | No soak was run |
| Critical workflows remain intact | **Supported, not fully proven** | No server code runs differently as deployed (the connection pool is behind a switch that is off); DOM and style comparisons; the suites in §18. No end-to-end pass over every workflow |
| Permissions remain intact | **Pass by construction** | No view, permission or query was touched; the one template condition added writes an attribute for the stylesheets |
| Data integrity is verified | **Pass by construction** | Two indexes and one planner setting; no row, constraint or write path changed |
| Existing UI remains unchanged | **Pass on phones, tablets and desktops; changed at laptop widths, reported, and kept at the owner's word** | §18: every computed style identical, and the final page compared with the original at four widths. Between 1,024 and 1,279 pixels, and wherever the sidebar is kept shut, a page now opens fitted for the width it has: on 13 of 61 pages a filter field, a tab or a table's columns are drawn differently from before — the fit the original reached after any resize. Also reported there: an attribute on date fields in closed rows (nothing drawn differs), and the scroll length of three pages before their lower sections have been scrolled to, an estimate in both builds |
| Existing functionality remains unchanged | **Supported** | as "critical workflows" |
| 50+ concurrent users remain stable | **Pass locally, before the changes** | §4. Not on production-shaped hardware |
| 100-user stress behaviour is measured | **Measured locally** | §4: p95 552 ms, 0 errors; the degradation threshold was not reached on this machine |
| Large-data behaviour is measured | **Measured** | 16,700 and 50,700 schools (§3 F8) |
| Long-session behaviour is measured | **Fail** | Not done |
| Performance regression tests exist | **Pass** | §18 |
| Before/after metrics are documented | **Pass** | §12 |
| Production-equivalent testing passes | **Not done** | Production was observed (§9), not tested with the changes; nothing is deployed |

By role, the pages measured before and after: CCEO 6 desktop + 4 phone + 2
laptop, PL 3 desktop + 1 phone, CD 4, Admin 1, IA 1 — all improved in the
work they cost, and all finish sooner. The other ten roles were covered by
the style and page comparisons, not timed.
By viewport: desktop **pass**; below 1280 pixels and phones **much
improved, and still seconds on a slow phone** (§12.3, §15).

The brief asks for about 90 % less unnecessary work where achievable and
forbids claiming it unmeasured. Measured, in main-thread work: **−92 %** on
one page (Strategic Priorities), **−23 % to −71 %** on thirteen other
desktop pages and −12 % on the lightest, **−45 % to −78 %** below 1280 pixels
and on phones at full speed, **−66 % to −79 %** on a slow phone. It is not
90 % across the system.

## 20. Decisions for the owner

1. **F11 — cost a day once per save. Done at your word of 6 October, on
   its own branch from current main** (§21.3): the cluster's bulk day runs
   45–61 % fewer statements for the same figures, proved table by table.
   Not committed, not deployed.
2. **Done, at the owner's word ("2", then "can you work on these"): the
   restyling below 1280 pixels (F18, F19).** One element added to a page
   restyles 18–75 of its elements there (161 on one page), where it was
   400–500 after F18 and over 2,000 at the start. **The same at desktop
   width: done on 6 October at the owner's word ("I meant desktop follow
   up"), §22.**
3. **Decided — the first frame stays held (§12.5, §18).** After the first
   report it was found to change what is seen at laptop widths (1,024–1,279
   pixels, or any width with the sidebar kept shut): the sidebar no longer
   slides shut after the page is drawn, and the page opens fitted for the
   width it really has — one more filter field or tab, or table columns a
   few pixels over, on 13 of the 61 pages. Shown the two side by side and
   asked whether to keep that or go back to how laptop pages open today,
   the owner answered on 5 October: "keep the new fit". Nothing further
   was changed for it; the gate in `e2e/performance-budgets.spec.js` holds
   it. Browsers that do not hold the first frame (Firefox, Safari before
   18.2) still open laptop pages the earlier way; bringing them into line
   would be a separate change and has not been asked for.
4. **F13 — database traffic on the private network. Half applied, by your
   hand** (§21.1): the app has been on `default-fra1` since 03:36 on
   6 October and is healthy. The one edit left is app-level `DATABASE_URL`
   to `${db.DATABASE_PRIVATE_URL}` (`.do/README.md`, step 1). I cannot make
   it: this session is not permitted to change live infrastructure.
5. **F6 — the connection pool. Built, rehearsed, switched off** (§14). It
   takes effect when this branch is deployed and `DB_APP_POOL=true` is set
   on the web component (`.do/README.md`, step 3).
   **F7 — a shared cache. Approved by you on 6 October; not provisioned,
   and it should wait for one small fix** (§21.2). Rehearsed against a real
   server, the deployed code answers the Country Director's dashboard and
   Analytics with an error, and a schedule save with an error after saving
   it, whenever the cache is unreachable. The fix is on its own branch from
   current main. Deploy it, then create the cache ($15.00 a month) and set
   `REDIS_URL` (`.do/README.md`, step 4). Creating it is also a change to
   live infrastructure and is yours to make.
6. **Security — the database accepts connections from anywhere.** Confirmed
   on 5 October: Network Access reads "your database is open to all incoming
   connections". The fix is a list of trusted sources (the app, and the
   private network's range), written out in `.do/README.md`, step 2. It is a
   security setting of your account, so it is for you to press; it takes
   effect at once and is undone by removing the entries.
7. **Committing. Done on 6 October, at the owner's word ("commit and
   push"):** this branch and the two of §21 are committed and pushed, and
   none is merged. This one is nine commits behind main and needs main
   merged into it, with its stylesheets rebuilt and its inventories
   regenerated, before it can be. The migrations are three small ones (two
   `CREATE INDEX`, one `ALTER ROLE`); both tables are small — a full scan of
   either takes 5–8 ms in production — so each index is built in a moment.
   They are numbered `core_schools` 0011, `fund_requests` 0019 and
   `system_health` 0003 against that base and are renumbered if main has
   taken those numbers.

## 21. After the report: the owner's go-ahead of 6 October

Shown the decisions of §20, the owner answered "2, 3, 3, 5. work on those":
the private network, the shared cache, and costing a day once per save (F11).
This section is what was done about each. The work sits in three places,
because main had moved nine commits past this branch's base and two of the
three changes had to be made on what is deployed:

| Worktree, branch | Base | Holds |
|---|---|---|
| `edify-perf-audit`, `audit/perf-forensics` | `3e558109` | everything in §11, and this report |
| `edify-save-path`, `perf/cost-a-day-once` | main `1242ac03` | F11 (§21.3) |
| `edify-cache-outage`, `fix/pages-survive-cache-outage` | main `1242ac03` | what the shared cache needs first (§21.2) |

Each was committed on its own branch and pushed on 6 October, at the owner's
word ("commit and push"). None is merged, so none is deployed.

### 21.1 The private network (F13)

**Done, by the owner's hand.** The first click of the change was refused to
me by the permission layer this session runs under, which treats a change to
live infrastructure as protected whatever was said in the chat; no other
route to the same change was tried. The owner connected the app to the VPC
himself at 03:36 on 6 October and changed app-level `DATABASE_URL` to
`${db.DATABASE_PRIVATE_URL}` at 08:49.

The first deploy with the new value failed, and DigitalOcean rolled back by
itself with no downtime. The `migrate` job's first connection had timed out
after the five seconds the settings allow (`psycopg.errors.
ConnectionTimeout`, raised from Django's start-up checks before a statement
had run). The database has no trusted-source list, so nothing refused it by
address. The next deploy, a push 29 minutes later with the setting
unchanged, connected at once. Why the one attempt found no route is not
known; `.do/README.md`, step 1, says what to do if it happens again.

That it is in force was read from the database, not inferred: its list of
current connections shows the application arriving from 10.114.0.2, its
address in the private network, where §10 (F13) recorded a public address.
From outside, readiness answers `"db": "up"`. **The gain is not yet
measured.** F13 expected about 2 ms less on every statement; the gap
between the readiness and liveness checks, which is mostly the cost of
opening a connection, reads 44 ms against 40–50 before, inside its noise.
The runtime log's database milliseconds per request are where it will show.

### 21.2 The shared cache (F7): rehearsed, and not yet safe to switch on

Creating the cache is the same kind of change and was not attempted. What
could be done without it was to find out what the deployed code does with
one. A Valkey 9.1 server was run on this machine and the application pointed
at it.

| Check | Result |
|---|---|
| The cache, session, throttle, health and oversight tests, run against the real server instead of the per-process cache they normally use | 150 passed, 1 skipped |
| Four workers on the 16,700-school copy with `REDIS_URL` set | readiness `"status": "ok", "cache": "up"` (it reads `degraded`, `unshared` in production today) |
| All 61 audited pages as 15 accounts through it | 61 clean |
| What it held afterwards | 26 keys, 6.5 MB (peak 10.7 MB): sessions, sign-in counters, dashboard snapshots, the oversight dataset. The 1 GiB node is ample |
| The server stopped while the application ran | readiness `"cache": "down"`, still HTTP 200; sign-in and six of seven pages tried still served; **the Country Director's Analytics page answered 500** |
| The server started again | readiness `ok` within a second, all seven pages clean, no restart needed |

**The finding.** On a per-process cache a page cannot lose its cache. On a
shared one it can, whenever the one node restarts (a single-node managed
cache has no standby, and is restarted for maintenance). The code was
written to survive that (`apps/core/cache_utils.py` fails open, the session
store reads the database, the throttle counts in the process), and
`CacheOutageTest` says every page must. It checked two pages. A crawl of
every argument-free page as every role, with the cache refusing every
operation, found nine addresses that did not survive, from four places with
no fallback:

| Place | What it did with the cache down |
|---|---|
| `apps/hr/accountability_cache.py`, the revision every cached analytics answer is filed under | read without a fallback: `/analytics`, `/analytics/country-director`, `/analytics/program-lead` answered 500. And it is advanced after **every activity save** commits: that write would have answered every schedule, reschedule and cancel with an error after the work had been saved |
| `apps/analytics/views.py`, four data endpoints | 500 |
| `apps/analytics/cd_dashboard_service.py`, the prior-year tiles | would raise inside the Country Director's dashboard when there is a prior year to compare |
| `apps/help_center/services.py`, the hourly marker of the Help panel's route sync | `/help/context` answered 500 for every role |

**The fix** (`fix/pages-survive-cache-outage`, five files): each of the four
now does what the rest of the code does. An unreadable revision is a token
nothing is filed under, so the answer is built rather than read from a
snapshot that may be out of date; the write after a save is attempted and
logged, never raised; the endpoints and tiles compute when they cannot read
and return what they computed when they cannot write; the Help marker falls
back to one kept by the process, so an outage does not bring back the
2,200-query re-sync on every request that the marker exists to prevent.
With the cache working, nothing behaves differently. `CacheOutageOnEveryPageTest`
is the crawl, kept: 17 role-by-role checks, and it failed for 15 roles before
the fix. The analytics, help, HR and core suites and the route crawl pass
with it: 2,847 tests.

The same was then tried for real, on the 16,700-school copy against the
local server, as the Country Director and as a field officer:

| With the cache stopped | Current main | With the fix |
|---|---|---|
| Country Director's `/dashboard` | **500** | 200 |
| `/analytics`, `/analytics/country-director` | **500** | 200 |
| `/api/analytics/dashboard`, `/api/analytics/coverage` | **500** | 200 |
| A field officer reschedules a visit | **answered with an error; the visit had moved** | 200, the visit moved |
| The cache started again | all 200 | all 200 |

**Before the cache is switched on**, in this order: deploy that fix; create
the cache; set `REDIS_URL`. Three things will then be different, all of
them what the code intends and none of them visible on a page:

- cached figures are shared by the four web processes (the point of it);
- sessions are read from the cache first and the database second;
- the sign-in limit of ten attempts a minute from one address becomes ten.
  Today each of the four processes counts its own ten, so up to forty get
  through. An office behind one address that signs in more than ten times
  in a minute will see the limit where it did not before
  (`RATE_LIMIT_LOGIN_PER_MIN` raises it).

### 21.3 A day costed once per save (F11)

**What was wrong**, confirmed again on current main: the cluster's bulk day
calls the single-visit pipeline once per school, and each call re-prices
every visit already on the day. Five schools on an empty day were priced
1+2+3+4+5 = 15 times; five more on that day, 40 times.

**What changed.** `apps.daily_visit_batches.services.each_day_priced_once()`
is a block inside which a visit joins its day and the day is remembered;
when the block ends, each remembered day is priced once, with all its
members, inside the same transaction. `bulk_schedule_cluster_visits` wraps
its loop in it. Nothing else about a school's scheduling changed: every
check still runs for every school, in the same order. Only joining a day
waits; a visit leaving a day or moving between two is priced at once, because
what follows it reads the result. `PRICE_A_DAY_ONCE_PER_SAVE=false` prices
after every school again, without a deploy.

**Why it is safe to wait.** The trace of a bulk save was read for anything
the per-school pipeline reads that the pricing writes. Outside the pricing
it touches the finance tables three times: the activity's own earlier cost
lines (none, for a new activity), whether the week's request has left the
owner's hands (the same answer whether or not the draft exists yet), and
the day record it creates. Its checks filter activities on school, type,
purpose, status, dates and owner, never on a cost or a period the pricing
stamps.

**Measured** on the 16,700-school copy: the same six saves, in the same
order, on two fresh copies of one database.

| Save | Priced after each school | Priced once |
|---|---:|---:|
| Five schools on an empty day | 1,059 statements | **584** (−45 %) |
| Five more on that day | 1,981 | **766** (−61 %) |
| Three on the next day | 576 | **405** (−30 %) |
| Two more join them | 604 | **423** (−30 %) |
| A day of one | 167 | 170 |
| Four on the day after | 775 | **473** (−39 %) |

Local times fell with them (the second save 2.3 s → 1.1 s). Production was
not measured: there each statement also pays about 2 ms of transit until
§21.1 is finished, so a save of 990 statements, production's median, should
lose about a second of that alone.

**The figures are the same.** The two databases were then compared: every
table either run wrote to, row for row, with the ids each run made up
replaced by names built from what their rows say.

| Tables | Result |
|---|---|
| `activity` (20 rows), `activity_schedule_cost_line` (40), `advance_request` (20), `weekly_fund_request` (1) and its lines (20), `fund_request` (1) and its items (20), `daily_visit_batch` (4), `transport_payment` (4), `core_activity_slot` (2), `target_ledger_dirty` (1) | **identical** |
| `activity_cost_snapshot`: 81 rows against 28 | every snapshot written the new way has a twin written the old way; the old way wrote 53 more, all superseded |
| `audit_log`, `domain_event_log`: 101 rows against 48 each | the same; the 53 more are all `activity.cost.calculated` |
| Request telemetry (session, presence, sign-in, interaction) | not compared |

One shilling added to one cost line of a copy is reported as a difference:
the comparison can fail.

`apps/daily_visit_batches/test_day_priced_once.py` keeps that comparison in
the suite, over every table of every app rather than a list: five plans (an
empty day; five joining five; a day with schools in a secondary district
among schools at home; a third day away that gives the second its night
back, which re-prices a neighbouring day; days of one, two, three and four)
are each carried out both ways on the same records and must end the same,
with the history of the new way contained in the history of the old. It
also holds that a member whose advance is with the accountant still stops
the whole day with the same sentence and nothing written, that the block
refuses to run outside a transaction, that a failure inside it prices
nothing, and a statement ceiling for the two heaviest saves (590 and 817
statements on those records, where pricing after each school takes 1,109
and 2,156).

**What does change, as agreed.** A visit added with four others has cost
snapshot 1, not snapshots 1 to 5, one "cost calculated" audit entry, not
five, and one event. Which school of a day carries the first share of the
pool, and any odd shilling, is decided by the order the visits were made
in, as before; that order is the same both ways.

**What it does not reach.** One reschedule of one visit already prices each
of its two days once (measured: moving a visit off a day of ten onto a day
of one prices 9 + 2 members, 626 statements). Its cost is the pricing
itself, about 35 statements a member in the single cost writer, which
locks, checks and rebuilds each member's lines, snapshot and advances. A
group reschedule or cancel is deliberately one transaction per activity, so
that one refusal does not undo the rest, and prices as it goes. Making the
writer itself cheaper is a different change to money code and was not part
of this decision.

## 22. The desktop follow-up, with main merged in (6 October)

Asked whether the doubled "3" of §21 had meant the fourth decision of §20,
the owner answered: "I meant desktop follow up", and later "open pr when you
are done". This section is that work. It is on `audit/perf-forensics`.

### 22.1 Main merged in

Main had moved eleven commits past the branch's base, to `503ea90a`: group
reschedule and cancel with a tick box on every planned activity, live
updates, bulk actions on the Core school list. The merge conflicted only in
generated files — the built stylesheets and the page, interaction, component
and traceability inventories, all rebuilt or regenerated from the merged
sources — and in the note beside the script-weight ceiling, which both
sides had raised: main to 144 KB for two new scripts, this branch for its
changes to two existing ones. Together they weigh 145.50 KB and the ceiling
is 146. The stylesheet ceiling stands (246.19 KB of 246.5). No migration
numbers collided.

Main's tick boxes are an `<input>` in every row, and one family of rules
that was left alone in §15 still files `input` and `select` under every
`:has()` anchor (the fields in a filter form's innermost `div`). So a page
restyles a few more elements for one insertion than §15's table says: 53 on
a phone's My Plan where it was 32, 77 at 1100 pixels where it was 31. It is
still 2–4 % of the page.

### 22.2 F20 — the pinned table column reads its answer from the cell

**What was left.** From 1280 pixels four rules decide which cell of a row
is the pinned identity by asking the first cell whether it holds a selection
box, `tr > :first-child:has(> box)`, and the last of them styles the name in
the cell *after* it. That one selector held a desktop at 9–19 % of the page
restyled per insertion, and was why two of F19's rewrites had to keep their
old form from 1280 pixels (§15).

**What changed.**

- `micro-ux.js` keeps a fifth fact: `data-edify-box-cell` on a row's first
  cell when that cell holds a box itself. It is written with the selector
  the rules carried, when a table is first seen and again in the observer's
  own turn when the table changes, like the other four. A table is now read
  once for everything that changed inside it in a turn; it was read once
  per change.
- The four rules read the attribute. None contains `:has()` any more, so
  they sit inside `@supports selector(:has(*))`: a browser that dropped them
  before still does.
- The page-header and caption rules of F19 are written one way again, at
  every width. The six `!important` declarations that the split had
  duplicated are gone and that ratchet is back at main's number.

Nothing is styled later than it was: these rules already wait for
`data-scroll-state`, which only that script writes.

**Measured**, the merged build without F20 against with it (1440×900,
16,700 schools, alternated, medians of five, nothing else running):

| Page | Main-thread work (ms) | Style recalculation (ms) |
|---|---:|---:|
| CCEO `/dashboard` | 811 → **779** (−4 %) | 575 → 545 |
| CCEO `/my-plan` | 520 → **490** (−6 %) | 313 → 286 |
| CCEO `/planning` | 409 → **392** (−4 %) | 201 → 185 |
| PL `/dashboard` | 1,360 → **1,231** (−9 %) | 963 → 833 |
| PL `/work-plan` | 578 → **545** (−6 %) | 369 → 335 |

Script time did not move (129 and 129 ms on the first row, 258 and 255 on
the fourth): keeping the mark costs nothing that shows.

| One element appended to a table cell, 1440×900 | Before F20 (§15) | With it |
|---|---:|---:|
| CCEO My Plan | 396 of 2,034 elements | **82** of 2,074 |
| CCEO dashboard | 239 of 2,610 | **102** of 2,791 |
| CCEO planning | 241 of 2,176 | **43** of 2,179 |
| CCEO Core Schools | 177 of 1,120 | **17** of 1,122 |

**Proof.**

| Check | Result |
|---|---|
| `e2e/has-rewrites.spec.js`: each of the five new selectors against the one it replaced, on the fixture | the same elements (33 to 276 of them) and the same ruling in 842 contests each; 40 pairs in all, Chromium and WebKit |
| `e2e/pinned-name-selector.spec.js`: the name's rule against the selector it first replaced, over every arrangement of a row's first two cells | the same elements, the same weight, both browsers |
| `e2e/maintained-facts.spec.js`: the attribute against `tr > :first-child:has(> box)` on every cell after each of 33 changes to the page (seven of them new: a cell put in front of the box cell, the box taken out, put back by a script, moved inside a plain label, a footer row) | agrees after each, both browsers |
| The same agreement at every animation frame while a page opens, and once settled: 61 pages at 1440, 1100 and 390 pixels | 12,377,885 checks, no disagreement |
| … and on the pages where a row really starts with a bare tick box. On the 61 audited pages none does (their tick boxes sit inside a label, which these rules never counted as the cell holding a box). Two templates do: the Staff directory and the project Planning page, where the rule is live for 25 cells. Four pages, four widths | 875,312 checks, no disagreement |
| Every computed style of every element, this build against main's stylesheets on the same page: 65 pages (those four added) at 1440, 1100 and 390 pixels | 195 page states, 459,096 elements, 375 million values, **0 differences** |
| … the four tick-box pages at 1280 and 1366 pixels, light and dark | 16 states, 19 million values, 0 differences |
| Each page as it opens with F20 against without it, every element's tag, classes, state and drawn box: 25 pages at 1440 pixels, the four tick-box pages at 1280 | all identical |
| Django: `core`, `frontend`, `system_health`, `core_schools`, `fund_requests` on the merged tree | 4,345 tests. 4,341 passed in the run. Four did not: the launcher-sensitive one of §18, and three wall-clock scale tests that were running while the machine slept with its lid closed; run again awake, their file passes (22 of 22) |
| 65 JavaScript unit tests; `ruff`; `makemigrations --check` | pass |
| `e2e/performance-budgets.spec.js`, with the desktop ceiling brought down from 35 % to the 15 % of the other widths | passes on the 16,700-school copy, the 700-school seed (3–7 % there) and a development-style server, with the built-against-source stylesheet spec |

**Not run**, as before: the whole Django suite, the whole browser suite,
Firefox, a real phone.

### 22.3 The branch as it stands, against main as it stands

One session, the owner at the machine, so the figures run a little higher
than the quiet ones above. "Before" is main `503ea90a` in full.

| Viewport, page | Main-thread work (ms) | Finished (ms) | Longest freeze (ms) |
|---|---:|---:|---:|
| 1440×900, CCEO `/dashboard` | 1,841 → **845** (−54 %) | 2,153 → **1,150** | 457 → 272 |
| 1440×900, CCEO `/my-plan` | 967 → **533** (−45 %) | 1,247 → **861** | 214 → 139 |
| 1440×900, CCEO `/planning` | 659 → **414** (−37 %) | 1,085 → **832** | 193 → 93 |
| 1440×900, PL `/dashboard` | 4,495 → **1,318** (−71 %) | 4,844 → **1,660** | 743 → 196 |
| 1440×900, PL `/work-plan` | 1,025 → **588** (−43 %) | 1,313 → **836** | 236 → 153 |
| 1440×900, CD `/dashboard` | 1,006 → **597** (−41 %) | 1,146 → **718** | 269 → 99 |
| 1440×900, CD `/strategic-priorities` | 11,520 → **906** (−92 %) | 12,159 → **1,421** | 10,208 → 360 |
| 1100×800, CCEO `/my-plan` | 1,271 → **603** (−53 %) | 1,555 → **885** | 367 → 141 |
| 1100×800, CCEO `/dashboard` | 1,931 → **981** (−49 %) | 2,221 → **1,318** | 508 → 277 |
| Phone, CCEO `/my-plan` | 1,558 → **569** (−63 %) | 1,838 → **881** | 480 → 154 |
| Phone, CCEO `/dashboard` | 2,561 → **869** (−66 %) | 2,822 → **1,135** | 1,065 → 289 |
| Phone, PL `/dashboard` | 6,689 → **1,372** (−79 %) | 7,178 → **1,720** | 929 → 191 |

Main is heavier than it was when §12 was measured: its own dashboard takes
1,841 ms where the branch's base took 1,232, with a tick box in every row
and two more scripts. The tables of §12 are the branch before this merge
against its base, and were not measured again.

### 22.4 What the pull request's own checks found (6 October)

Opening the pull request ran, for the first time on this branch, what only
CI runs: the whole browser suite against a freshly seeded database, the
Django suite under the parallel runner, and the two code scanners. Every
local run had been this branch's own specs and the Django suite in one
process on one migrated database. CI found four things. Nothing a user sees
changes; one is in a script that ships.

**1. The script that keeps the five facts read every arrival on its own
(ships).** When a parent and its children are appended one by one in one
task (a table built row by row, thirty fields in a loop), `micro-ux.js` read
each of them for tables, heading rows, rails and search boxes, where the
page's enhancement pass has always read only the outermost.
`e2e/ui-work-batching.spec.js` exists to count exactly that: it allows no
scan of a nested arrival and counted thirty. What arrives in one turn is now
reduced to its outermost elements and each is read once. The marks are the
same: every element read before is inside an element read now, and no mark
reads another. Held by:

- the guard itself, 0 scans, Chromium and WebKit;
- `e2e/maintained-facts.spec.js`, now 35 changes (two new: a section that
  arrives and is filled piece by piece in the same turn, and a table that
  arrives and ends the turn inside another arrival). Its check was also
  moved: it used to look one task after each change, by when a later pass
  over the page could have put a fact right a frame late. It now looks within
  the turn of the change, and again one task later. With the reading of
  arrivals taken out on purpose the spec fails on two changes; before the
  move it passed;
- `e2e/has-rewrites.spec.js` (40 pairs) and `e2e/pinned-name-selector.spec.js`
  in both engines; the 65 script unit tests; shell JavaScript 145.59 KB of
  146.

**2. The first-frame gate counted htmx announcing a fetch (the gate, not the
page).** The Program Lead dashboard fetches two sections after it is shown.
htmx marks each fetching element `htmx-request`, then `htmx-swapping` and
`htmx-settling`, and takes each name off again: seven class writes after the
first frame, on two elements the server sent, whatever the data. The gate
allows the larger of 5 late writes and a tenth of the page's. On the
16,700-school database that dashboard stamps 1,855 classes and the seven
went unnoticed; on CI's fresh seed it stamps 55, the allowance is 5.5, and
the gate failed twice with "7 of 55". The same seven, and the same message,
were reproduced here on a database seeded the way CI's is. The recorder now
sets aside a class write whose only change is one of htmx's four names
(0 of 46 on the fresh seed, 0 of 1,846 at scale; nothing else is treated
differently), and a control test makes each kind of write and counts it: an
announcement 0; a class stamped, a class stamped in the same write as an
announcement, and the same classes written again, 1 each. The spec's opening
comment says its gates read the same on a laptop and on a loaded runner.
This one read differently on a small database, which no run of mine used.

**3. A Django test looked for a row that a copy of a database does not
carry (the test).** `manage.py test --parallel 4` gives each worker a copy
of the migrated test database. PostgreSQL keeps a role's default for a
database (`pg_db_role_setting`) beside the database, not in it, so a copy
has none, and the test for migration `system_health.0003` (F5, §11 row 9:
pooled sessions run with JIT off) found none in a worker. It now runs the
migration's own two statements inside its transaction and reads the
catalogue after each (reset: absent; set: `jit=off`; reset: absent), and a
second test holds that those statements are the ones the migration applies
and reverses. Run here under the parallel runner with two workers, the test
as it was fails in both and the new ones pass. Outside tests it says one
thing worth knowing: a production database that was copied rather than
migrated would not carry the default either. `/api/health/ready` answers
`"db_jit": "on"` and `"status": "degraded"` in that case, which is what that
answer is for.

**4. Two patterns in audit harnesses (not the application).** The code
scanner reads `scratch/` like any other code: a regular expression in the
style oracle with a repeat inside a repeat (now one optional tail, the same
language: 0 of 89 million strings and 0 of the app's 85,716 selector parts
answer differently), and a one-pass removal of script tags in the first-paint
probe (now repeated until nothing moves; 156 of 156 real outputs identical).

The two sibling branches met the same kind of thing. The cache-outage branch
(§21.2) and the day-priced-once branch (§21.3) each moved lines that two
checked-in records describe, and CI tests a pull request as it will be once
merged: both now carry main and records rebuilt on that tree. The
day-priced-once proof's test file had two lines the security linter asked
about (a label digest marked as not for security; a query over model-registry
names annotated with its reason). The rebuilds showed one thing no branch
causes: main's committed traceability matrix, main's own code traced here
the same afternoon, and the three branches with main merged in name 244, 243
and 242 files, the three branches agreeing with one another. A presence
write lands under whichever journey is running when its interval comes
round. That is the tracer's, and is reported to the owner as its own task.

### 22.5 Main kept moving: three more merges, and a migration renumbered (6 October, evening)

Three pull requests reached main while this one was open after §22.4, and
each made it conflict:

- **#226** (the day priced once, §21.3) and **#225** before it each rebuilt
  the traceability matrix on their own tree, so the fingerprint conflicted;
  it was rebuilt on the merged tree each time. Where the two changes meet,
  in the bulk save, the day-priced-once proof was run on this branch's code:
  its statement ceilings and its whole-database comparison hold.
- **#228** (My Plan's training names) merged without a conflict.
- **#229** (training ceilings) conflicted on five generated files, all
  rebuilt on the merged tree in the documented order, and brought the one
  real clash: its `core_schools` migration and this branch's index were both
  numbered `0011`, which Django refuses as two heads. As §20 said it would
  be, the index is renumbered, to `0012`, behind main's. Main's `0011` moves
  data and reaches production when main deploys, which is before this branch
  can; an index does not mind the order it is built in. Applied in that
  order to the 16,700-school copy, main's refile gave back 0 slots and the
  index was built.

Two of the browser suite's own tests also had to learn to wait (§22.4 found
the gate that counted htmx; this is the other side of the same coin). After
making the viewport a phone's, `form-refinement` read a field's font size at
once and `compact-drawers` measured a drawer's box at once. Both values
arrive by a transition, and both tests only ever read after it because the
page was busy: with main's scripts and styles the page first answers 2,263
to 2,319 ms after a resize, on this branch 121 to 169 ms, so the read now
lands inside the move (14px to 15.8px where 16px is expected; a sheet 5.8px
from the edge). Each now reads where the value comes to rest and asserts
what it asserted before. The suite's `reducedMotion` setting, which would
have hidden this, is written where the test runner does not read it, on main
as well; that is reported to the owner separately and not changed here.
