# A+ Performance, Reliability and Code Optimization Under Functional and Visual Parity — 2026-09-24

Branch `claude/nifty-pasteur-7xolto`. Baseline: `086b498` (main at the start,
PR #127). Every figure below comes from the repository's own scripts run in an
isolated environment built for this session. No request, load or write was
sent to production or staging; neither was available to this session.

**Decision: NO-GO** (§12). The branch removes the measured freezes and N+1
queries listed in §4 without changing a single rendered byte that the change
did not deliberately make deterministic (§3), and it is safe to merge and
deploy as an improvement. It does **not** clear the release gates of the
brief: the production web service is one instance on one vCPU, and the 2-hour
sustained test, 8-hour soak, fault injection, restore, rollback and canary
gates could not be run here.

## 1. Environment and baseline record (28, 8.1)

| Item | Value |
|---|---|
| Repository / branch | `O-Mario88/edify-planning-tool` / `claude/nifty-pasteur-7xolto` |
| Baseline commit | `086b498` (a `git worktree` of it ran beside the branch for every before/after pair) |
| Release candidate | the head of this branch; the measured code is `8ca581b` (later commits add this report only) |
| Migration state | baseline `audit.0007`; release adds `audit.0008` (one column widened, §5) |
| Runtime | Python 3.13.12, Django 5.2.17, PostgreSQL 16, Redis 7 (local), openpyxl 3.1.5 |
| Settings | `config.settings.dev` for the route sweep and golden master (the repository's convention), `config.settings.loadtest` (`DEBUG=False`) for load |
| Templates, CSS, JavaScript, service worker | **unchanged** — `git diff 086b498 -- templates static assets '*.js' '*.css'` is empty |
| Dependencies | unchanged — no package added or removed |
| Realistic dataset | demo seed grown with `scripts/scale_local_domains.py people` → `scale_local_dataset.py --schools 49300` → `scale_local_domains.py domains` → `salesforce`: **50,000 schools, 150 CCEOs, 16 Programme Leads**, 74,210 activities, 65,096 SSA records, 520,768 SSA scores, 115,862 cost lines, 115,602 advances, 79,866 evidence records, 35,832 notifications, loans, BT cases, leave (≈3× production's school count; ≈330 schools per officer, which is production's shape) |
| Demo dataset | `seed --demo` (700 schools), for the whole-surface golden master |
| Roles | 15 accounts: CCEO, PL, CD, IA, Accountant, HR, Project Coordinator, Partner Admin, Partner Field Officer, Business Transformation, MFI Admin, MFI Officer, Regional Programme Lead, RVP, Admin |

## 2. What was measured first (9)

`scripts/route_timing_sweep.py` requested every argument-free GET route as
every role on the realistic dataset with the baseline build: **7,500
requests, 2,024 HTTP 200, zero 5xx**. HTTP 200 latency: p50 28 ms, **p95
1,837 ms, p99 4,984 ms, max 19,580 ms**; 201 pairs over 600 ms, 165 over
1 s, 57 over 3 s; 34,279 queries; 59 pairs repeated one statement 10 times or
more. Slow statements were collected from PostgreSQL's log
(`log_min_duration_statement=150`), and every candidate below was profiled
with `scripts/profile_request.py` before it was changed.

**Caveat.** This sweep, like the later ones, ran with the local Redis as the
cache, shared with other processes working on other database copies under the
same build namespace; a cached page could have been served from another
run's snapshot. The timing cohort (§6), the load tests (§7) and the final
golden-master comparisons each used their own Redis database or none.

## 3. Golden master: functional and visual parity (8, 12)

**Method.** `scripts/parity_snapshot.py` (new) records, for every route and
role, the status, redirect target, HTMX headers and the response body with
per-request noise masked (CSRF tokens, CSP nonces, correlation ids, ISO and
clock times, relative ages, a fresh authenticator secret, and ids of rows a
GET itself created during the capture). Workbooks are compared by their sheet,
style and shared-string XML. Since no template, stylesheet or script changed,
identical HTML is identical pixels; the byte comparison is therefore both the
functional and the visual parity proof for the server-rendered surface, and
it is stricter than a masked screenshot.

**Noise floor.** Two captures of the *baseline* on two fresh copies of the
demo database: 7,500 responses, **7 differ** — all the Admin's unread
notification badge count, which depends on notifications GETs generate
during the run.

| Comparison | Responses | Identical | Explained differences | Unexplained |
|---|---:|---:|---|---:|
| Demo estate, every route × 15 roles, baseline vs release | 7,500 | 7,320 | 112 clock minute stamps; 30 Admin badge counts; 29 time-dependent panels (presence "Online since … 2m", "who is on leave now"), confirmed by re-capturing both builds side by side (only the rows below then differed); 9 deliberate re-orderings (below) | **0** |
| 50,000 schools, the 57 changed routes + 8 tab/drilldown variants × 15 roles | 975 | 935 | 21 Admin badge counts; System Health telemetry of the capture itself; presence durations; 4 map-metric values that the **baseline itself** produces differently on every uncached run (§9, F-B); deliberate re-orderings (below) | **0** |
| Service outputs compared as JSON on the 50,000-school copy (each fix, §4) | 20 payloads, up to 24 MB each | 18 | 2 identical once rows that tie are put in the same order (the two re-orderings below) | **0** |

**Deliberate re-orderings (brief §14).** Two lists had no total order and
changed between loads of the *baseline*: Core School Oversight ordered schools
by name only (several schools share a name), and Admin Team Plans ordered by
date fields only under a 500-row slice (so tied rows swapped in and out of
the page). Both now end with `id`. On every page affected the rows are the
same multiset of lines as the baseline's; only the order of rows that tie
changed, now fixed for every load.

**Scope limit.** The golden master covers every argument-free GET route and
the listed variants. It does not replay POST workflows; those are covered by
the unchanged test suite (§8), which passes.

## 4. Freeze and N+1 register (10, 13)

Every entry was reproduced on the 50,000-school copy, fixed at its cause, and
compared with the baseline's output on the same data (byte-identical unless
the note says otherwise). Times are single-process, warm, one request at a
time.

| # | Page and role | Root cause | Fix | Before → after | Parity evidence | Regression test |
|---|---|---|---|---|---|---|
| F-1 | `/leave/approvals` (PL, CD, RVP, HR) | `is_authorized_approver` ran 3 queries per pending leave (policy, reviewer's coverage, one supervisor row) in three loops | `approval_lookups()` shares the reviewer's lookups for read-only listings; decisions still read live rows | **1,125 → 84 queries** (PL), 1,175 → 134 (CD); page 1.1 s → 0.17 s (PL) | new test: every leave × every reviewer equals the unshared rule | `apps/hr/test_leave_approval_queue_queries.py` (3) |
| F-2 | `/projects/my-plan` (PL, CD) | District filter joined district × schools × activities × clusters × activities, then `DISTINCT` (4.06 s) | two `IN (subquery)` tests over `Activity.all_objects` (the join ignored soft deletion too) | **4.0 s → 0.29–0.33 s** for every role (query 4,060 → 73 ms) | golden master | — |
| F-3 | CD analytics cluster table | ~45,000 SSA records and ~360,000 prefetched scores built as model instances | plain rows in the same order; the record set as a subquery | 5.3 s → 1.1 s | 737 KB JSON identical | covered by existing CD analytics suites |
| F-4 | CD analytics lead table | a school COUNT, an advance SUM and a full pass over every activity, per lead | one read each for the country, per-lead answers by intersection | 1.34 s → 0.66 s | identical | existing suites |
| F-5 | CD analytics CCEO snapshot | 50,000 ids bound as one placeholder each, twice | one array parameter | 1.54 s → 1.05 s | identical | existing suites |
| — | **CD dashboard payload as a whole** (F-3..F-5) | | | **13.7 s → 7.4 s** | 1.0 MB identical | |
| F-6 | `/analytics/country-director/drilldown` | unprimed: a ledger rebuild and 3 reads per lead team (16×) | one roster read, pooled per team (only when no allocation contract exists, where every team took that path) | 4.4 s → 2.0 s (service); page 3.1 s → 2.2 s, 338 → 183 queries | identical (default and `drill=pl`) | existing suites |
| F-7 | `/team-targets/matrix` (CD, PL, RPL) | a rebuild and 3 reads per person | `rebuild_many` + one read per table, same arithmetic per person | **764 → 13 queries**, 1.8 s → 1.1 s (CD page) | new test: every row equals the per-person computation for 3 area filters | `test_matrix_rows_equal_the_per_person_computation` (fails on old code: 21 → 49 queries) |
| F-8 | `/budgets/overview` (CD, IA, Accountant) | 17 rollups (year, 4 quarters, 12 months), each 3 full-year scans | `get_budget_rollups`: the same joins and sums grouped by the column each call filtered on | page 2.0–2.2 s → 1.1 s; 74 → 26–32 queries | identical, plus a new equivalence test over every advance status | `GroupedRollupTests` |
| F-9 | `/core-schools-oversight/` (CD, IA, RPL, RVP, Admin) | built every item in the country over two fiscal years to keep core-school work | `core_work_only` narrows in SQL to a superset of what the page keeps (precedent: `cluster_work_only`); activity rows read with `.only()` | page 7.4–8.2 s → 3.1–3.2 s for the five country roles; planned work 5.1 s → 0.7 s (24 MB identical) | identical after the ordering fix | oversight oracle suite |
| F-10 | Oversight cost totals (team, country, cluster, core oversight and exports) | 74,000 ids as a literal array | the activity queryset as a subquery | 456 → 163 ms per call | oversight oracle (frozen old code) passes | `test_oversight_oracle` |
| F-11 | `/admin-ops/team-plans` | 2 queries per row for cost lines and advances | the prefetch My Plan uses; total order (above) | **655 → 11 queries**, page 1,079 → 420 ms | identical under the same order | `test_team_plans_cost_does_not_grow_with_the_rows` (fails on old code: 9 → 27) |
| F-12 | `/target-distribution` (CD, HR) | approved leave read per person (166); 50,000-id literal list | `prime_leave_days` (existing) + assignments as a subquery | page 962 → 237 ms (IA); 179 → 14 queries | identical | existing oracle |
| F-13 | Plan workbooks (`/work-plan/export.xlsx` and every plan export) | openpyxl hashed 3 styles per cell (~250,000 lookups) | first cell of a band registers; later cells take the same indices | styling 1,323 → 131 ms for 4,220 rows | new test: saved workbook XML byte-identical to a frozen copy of the old loop | `test_the_body_styling_writes_the_same_workbook_as_before` |
| F-14 | Team Oversight flagged schools; dashboard urgent-schools card | full 120-column activity rows read for 6 columns | `.only()` with the school joined whole | 671 → 548 ms | identical | existing suites |
| F-15 | `/planning` (CCEO, PL, CD) | peer scores read per cluster on the page: 3 queries × up to 15 clusters | `_latest_scores_by_cluster` reads every cluster on the page in 3 queries and splits by cluster | **112 → 70 queries** (CCEO); time unchanged at ≈ 0.4 s (the queries were cheap; the page's time is Python) | golden master: 60 responses × 15 roles identical | `test_cluster_latest_scores_batch` (4; fails on old code: 12 → 6) |
| F-16 | `/core-schools` (IA, CD, Accountant, Admin) | the same SSA score totals read twice (Intervention Impact, staff/partner split) and the same latest-record average twice (KPI strip, benchmark), each over a literal list of every scoped record id | each read once per request, keyed by the scope's SQL; latest records as a `DISTINCT ON` subquery | **IA 2,172 → 1,653 ms**, 83 → 73 queries; CD 2,286 → 1,823 ms | helper outputs identical (IA, CD, PL, CCEO); page differences only where two baseline captures differ from each other (F-G) | `test_the_page_reads_shared_scores_once_with_the_same_answers` (fails on old code: 2 → 1 score reads) |
| F-17 | `/ia/dashboard/` portfolio change (and five other `classify_pairs` callers) | rule lookup and date interval decided for each of 160,208 domain rows | decided once per (domain, country) and once per pair of dates | classification 329 → 291 ms on production-shaped rows; portfolio 1.31 → 1.14–1.18 s | full classification output hash identical; portfolio JSON identical (IA, CD, PL) | `test_classify_pairs_equivalence` (randomized, every branch, against a frozen copy) |

## 5. Reliability defect fixed

**R-1 Lost event-stream projections.** `DomainEventLog.aggregate_id` was
`varchar(30)` while the `AuditLog.subject_id` it projects is 128. Every
audited subject id longer than 30 characters (for example the denied-access
event for `team_planning_oversight_drawer`) committed its audit row but
dropped its event-log row and realtime push with a logged
`StringDataRightTruncation`. Migration `audit.0008` widens the column to 128.
In PostgreSQL a varchar length increase is a catalogue change: no table
rewrite and no index rebuild, safe online. Rollback: the previous image runs
unchanged against the wider column.

**R-2 Admin Team Plans showed no next action (owner-approved visible
change).** The row read `next_action["label"]`; `compute_next_action`
returns `"text"`. Every row showed "—" in Next Action and the "No next
action" tile counted every row. The column now shows the same step My Plan
offers the officer, and the tile counts only rows whose only action is the
default "View Details" (no owner step). This is the one deliberate visible
change in the branch, made on the owner's instruction after §9 raised it;
`test_team_plans_shows_the_canonical_next_action` fails on the previous code
("—" instead of "Start") and passes now.

**R-3 Map SSA figures changed between loads (owner-approved).** The
regional map's sub-county, district and sub-region means come from
PostgreSQL's `AVG`, which adds floats in whatever order the plan visits the
rows; rounded straight to two places, a mean at a rounding edge read 5.42 on
one load and 5.43 on the next, and best/worst interventions were chosen on
the raw means in the order the grouped rows arrived. `map_score` (beside
`_ssa_score`, which already solves this at one decimal) rounds to six places
before two, and best/worst are ranked on that value with ties broken by
intervention code. Three uncached runs of `country_map_context` on the
50,000-school copy, which previously all differed, are now byte-identical;
6–8 of 99,112 values differ from earlier runs, each by at most 0.01, and no
best/worst name changed. `test_map_score_stability` pins a real case:
`[6.6, 8.4, 8.1, 7.8]` averages to 7.7250000000000005 forwards and 7.725
backwards, which plain rounding shows as 7.73 and 7.72.

**R-4 The fiscal-year rollover ran inside a user's request
(owner-approved).** When the scheduler had not yet rolled the year over,
`FiscalYearRolloverMiddleware` ran the whole rollover (600–2,900 queries,
9–12 s at 50,000 schools) inside the first signed-in request of each
process, and other processes waited on its row lock. It now claims the
rollover and runs it on a background thread in the same process, and every
request, including the one that noticed, returns at its normal speed (a
2-second stand-in rollover: the triggering request 2.00 s → 0.00 s). The
guarantees are unchanged: one rollover per process at a time, the retry
back-off after a failure, and no rerun once the year is done. The rollover
is idempotent and commits all-or-nothing behind its `FiscalYearRollover`
marker, so a process that stops mid-way rolls back and the next signed-in
request, in any process, or the scheduler starts it again. One visible
difference: pages loaded in the seconds while it runs show the year as it
was before the rollover, where before the first user waited for it.
`test_rollover_concurrency` covers the non-blocking claim, single run,
back-off and anonymous requests, and a new `TransactionTestCase` runs the
real rollover on the thread's own database connection and reads its
committed marker back.

**R-5 Core Schools lists had no order (F-G, owner-approved 2026-09-25).**
The main list ordered by `created_at` alone, and imported or seeded schools
share a timestamp, so the rows on a page changed between loads. The
Attention Needed card listed plans in the table's physical order. The list
now ends with `id` (newest first is unchanged) and the card is ordered by
school code. Two captures of the release now agree on all 90 `/core-schools`
responses; two captures of the baseline differed on 20.
`test_core_school_lists_have_a_total_order` fails on the previous code and
passes now. The parity capture now finishes a pending fiscal-year rollover
before it starts, since pages captured while the R-4 thread ran saw the
previous year.

**R-6 Leadership pages rebuilt the achievement ledger on every load (F-D,
owner-approved 2026-09-25).** Every write to a ledger source (activity, SSA
record, Most Significant Change story) now marks its officer and fiscal year
dirty in the same transaction. The mark is one upsert into
`target_ledger_dirty` (migration `targets.0007`, which starts everyone
marked). Team Targets, CD/RVP analytics and the team roster rebuild only the
marked members of their roster, then clear exactly the marks they answered;
a mark written during that rebuild survives. A change saved through the ORM
is therefore on the next load exactly as before, and a page with nothing
marked writes nothing.
- Bypasses: queryset `.update()` and bulk writes skip signals. The one bulk
  write that reaches the ledger, SSA import's `bulk_create`, marks
  explicitly. A change to the target areas marks everyone.
- Backstop: `target_ledger_sync` still rebuilds every active officer every
  30 minutes.
- Unchanged: the officer's own My Targets page and export still rebuild
  that one person.
- Tests: `test_ledger_sync` saves every kind of change (new, verified,
  reassigned, moved across the year boundary, returned, deleted) and checks
  that a full rebuild afterwards changes nothing. Two page tests that
  changed status with `.update()` now save, as the workflows do.
- Measured: CD `/team-targets` 2,704 → 1,664 ms.

**R-7 Layout shift after the first paint (P-4, owner-approved 2026-09-25).**
Each cause was traced by recording shift sources and a filmstrip under the
Slow 4G / 4× CPU profile, then fixed where it arose. The final rendered
state of every page is unchanged; only what paints before the scripts run
differs.

| Cause | Fix | Pages |
|---|---|---|
| Filter disclosures render open, and `mobile-ux.js` closed them on phones after the first paint | a head flag keeps their body out of a phone's layout until the script has set their state; the page's `load` event clears the flag if the script never does | Planning, Schools, Analytics |
| The KPI strip's "Swipe for more" navigation shipped `hidden` and appeared when `kpi-strips.js` ran | an inline check right after the strip makes the same overflow test while the page is parsed | every page with a context strip |
| "What needs you now" category panels were `x-cloak`'d, although all are visible in their initial state | not cloaked | CCEO dashboard |
| Oversight tab strips cloaked every panel, including the one Alpine opens | `tab_initial` (same rule as `tabState`, unit-tested) leaves that panel uncloaked | Team, Core School and Cluster Oversight |
| Oversight period fields: all four painted, then three hidden; `micro-ux.js` then added `edify-filter-field` | the unused fields render hidden and every field carries the class | Team Oversight, Partner Monitoring |

| Page (cold, Slow 4G, 4× CPU) | Before | After |
|---|---:|---:|
| CCEO `/planning` 412 px | 0.354 | 0.025–0.032 |
| CCEO `/dashboard` 412 px | 0.153 | 0.035 |
| CCEO `/schools` 412 px | 0.178 | 0.004 |
| CD `/analytics` 412 px | 0.182 | 0.000 |
| CD `/core-schools` 412 px | 0.132 | 0.039 |
| PL `/team-planning-oversight/` 412 px / 1280 px | 0.171 / 0.427 | 0.024 / 0.009 |
| CD `/core-schools-oversight/`, `/cluster-oversight/` 1280 px | — | 0.004 / 0.007 |

R-7 also had a spacing side effect, found by the scrolled comparison below
and fixed in `2262994`. The inline strip check was a `<script>` after the
strip; inside a `space-y` card that made the strip no longer the last child,
so the card grew by 16 px. The check now sits inside the strip's own
navigation.

**R-8 Pages shipped content no one could see yet (P-5, owner-approved
2026-09-25).** Four changes, each rendering the page in the state it had
before:
- Oversight tab strips render only the panel `tabState` opens on. Every
  other panel is an Alpine `<template x-if>`, created when its tab is picked,
  then `htmx.process`'d. `micro-ux.js` already dresses inserted content
  through its MutationObserver.
- Long selects carry their options in `<template data-lazy-options>`.
  `micro-ux.js` expands them when their disclosure opens or the select is
  focused or pressed, keeping the server's order and the chosen value. Until
  then the select holds its first and chosen options, so it reads and
  submits as before, and an inert list does not count as an empty filter.
  This covers Analytics sub-county and cluster, the Loans follow-up's linked
  loan, and the Schools sub-county and bulk pickers.
- The CD dashboard's district rows exist only while their region is open.
- Two tables are now paged, as the other tables on their pages already are.
  These are the only visible changes: Team Oversight's staff with flagged
  schools (5 per page) and SSA's intervention gaps by district (10 per page).

| Page (1280 px, first load) | Nodes before | Nodes after |
|---|---:|---:|
| Cluster Oversight (CD) | 33,123 | 2,061 |
| Core School Oversight (CD) | 28,492 | 2,317 |
| Team Oversight (PL / CD) | 22,406 / 14,988 | 3,201 / 3,037 |
| Loans (BT) | 9,332 | 1,342 |
| Analytics (CD) | 8,670 | 3,536 |
| SSA (IA) | 4,406 | 2,148 |
| Schools (CCEO) | 3,653 | 2,823 |
| CD dashboard | 5,238 | 3,606 |
| Cluster Oversight (PL) | 5,077 | 5,077 |

Still over 3,000 nodes, with the reason:
- CD dashboard and Analytics: a script-drawn SVG map (2,175 nodes), one path
  per area, which its hover depends on.
- PL Cluster Oversight: eight ApexCharts families (about 480 SVG nodes
  each). Drawing charts only near the viewport was tried and reverted: the
  plot height held for an undrawn chart is not the height ApexCharts
  draws, so card rows changed height.
- Team Oversight: 37–201 nodes over. The rest of the page is one open
  officer's tables and the shell, which renders the sidebar twice (phone
  drawer and desktop rail, about 260 nodes each).

**Visual verification (2026-09-25).** Every page in the browser set was
compared as screenshots. The shell scrolls `<main>`, not the document, so
each page was stepped through in 800 px screens rather than one full-page
shot. That is 18 pages × 390 and 1280 px, 138 screen pairs, previous build
against this one, on copies of the same 50,000-school database.
- 94 pairs identical.
- 44 differ, every difference explained:
  - The two paged tables above.
  - The Core Schools order (R-5).
  - One count on Team Targets (67 → 49 core packages). This is data drift
    between the two database copies, not code: `/core-schools` creates up
    to 100 missing core plans per page load, and the two servers had served
    different numbers of those loads (800 and 600 plans since the pristine
    copy's 0). See finding F-H.
  - 1–9-level anti-aliasing specks of 2–50 px near text edges.
- Switching officer tabs and opening every lazy select drew the same rows,
  options and table styling as the previous build.

**R-9 Render-blocking bytes (P-3, owner-approved 2026-09-25).** Measured
first, with the static files built exactly as production builds them
(hashed and compressed by `collectstatic`). Throttle: 150 ms round trip,
1.6 Mbps, 4× CPU slowdown.
- **Request count is not the constraint.** The browser discovers all 17
  stylesheets and 3 head scripts at about 190 ms and fetches them together.
  The link is full, so first paint waits on bytes: 229 KB must arrive before
  any paint on the smallest page.
- **Controlled experiment.** One captured page, served by one server in
  each variant, median of 5 cold loads:

  | Variant | Blocking KB | First paint |
  |---|---:|---:|
  | As shipped (gzip) | 229 | 2,008 ms |
  | Stylesheets bundled in cascade order (gzip) | 218 | 2,112 ms |
  | Bundled, head scripts deferred (gzip) | 186 | 1,976 ms |
  | As shipped, Brotli | 184 | 1,808 ms |
  | Bundled, Brotli | 152 | 1,728 ms |
  | Bundled, deferred, Brotli | 124 | 1,620 ms |
  | Floor: Brotli CSS only, no font preload, no scripts | 124 | 1,248 ms |

- **Implemented: Brotli.** Only Brotli helps without changing a decoded
  byte. With the `Brotli` package installed, WhiteNoise writes a `.br` copy
  of every static file at `collectstatic` (734 files, build 18.6 s) and
  serves it to browsers that accept it.
  - All 734 decompress to their source byte for byte, and the hashed names
    are unchanged.
  - Across the 18 pages, cold transfer fell 59–106 KB per page (about 13 %).
  - First paint improved on 15 of 18 pages, typically by 100–490 ms. The
    other three are single samples on pages whose server time dominates.
  - `test_collectstatic_writes_brotli_copies` fails if the package goes
    missing. `pip-audit --strict` is clean; 1.2.0 closes CVE-2025-6176.
- **Not implemented: bundling.** It saved nothing measurable (+104 ms, within
  noise). One large file also loses the per-file cache on a stylesheet
  change. The proposal's premise, that round trips were the cost, did not
  hold.
- **Not implemented: deferring `htmx`, `chart-standard.js` and
  `alpine-components.js`.** Worth about 100 ms. Page templates call
  `htmx.ajax`, `EdifyChartSystem` and `Alpine.data` from their own scripts,
  and the `feature_head_js` block runs page scripts in the head. Deferring
  would change when those run, a behavioural risk out of proportion to the
  gain.
- **Cold first paint ≤ 1.2 s cannot be reached at this throttle** without
  removing CSS. Even the floor variant, which drops the font preload and every
  script, paints at 1,248 ms. The render-blocking CSS decodes to 1.3 MB with
  about 11,000 selectors, most unused on any one page. Meeting the gate cold
  needs per-page critical CSS or a pruned stylesheet set. That can change
  rendering on some page, so it would need its own approval and a full visual
  pass.
- **Warm loads (files cached, the usual case for staff).** First paint is
  under 1.2 s on 11 of 18 pages. The other seven wait on the server (TTFB),
  which P-1 and P-2 address.

**R-10 The CD dashboard waited for every figure before its first byte (P-2,
owner-approved 2026-09-25).** A cold build of the Map view takes 5–8 s at
50,000 schools: KPI strip 2.5 s, map 1.9 s, Programme Lead table 1.0 s,
geography 1.1 s.
- **What changed.** When the dashboard's snapshot (and the map's, on the Map
  view) is not built yet, the page renders its header, scope counts, filters
  and phone header at once. The body then fetches itself from the same
  address, by the path the filter form already uses. The phone header's
  primary action is held as an invisible placeholder of the same size and
  arrives with the body, swapped in place by id.
- **What did not change.**
  - A warm dashboard renders whole, byte for byte as before (test).
  - The body that arrives is the one the filter form fetches (test).
  - With caching off, which is how the test settings run, nothing is
    deferred.
- **What users see now.**
  - On a cold load, a "Building the country dashboard…" placeholder sits
    where the body will be. Nothing follows it on the page, so the body's
    arrival moves nothing (CLS 0.000).
  - Cold first paint fell from 10,128 ms to 2,028 ms under the throttle, and
    from 9,736 ms to 444 ms unthrottled. The body still arrives 8–9 s after
    the request, as before: this moves the wait, it does not remove it.
    `browser_metrics.cjs` reports LCP when it settles at 2.5 s, so its cold
    LCP for this page is the shell's, not the body's.
- **Visual check.** The finished page, cold, against the baseline cold, in
  800 px steps: Map view at 390 px identical; at 1280 px one 10 px
  anti-aliasing speck. Operations view: the only differences are the live
  "Who's Online" times.
- **Not deferred.** `/analytics` and `/ia/dashboard/` do not have a snapshot
  cache or a body swap path to reuse. Deferring them means building those
  first, a larger change that has not been made.

## 6. Response-time results (7.3, 9)

**Method.** The cohort is every route × role pair that took over 1 s in the
baseline sweep of the realistic dataset: **165 pairs**. Each pair was timed
in-process by `route_timing_sweep.sample` (one warm-up request, then the
median of three), the baseline and the release at the same time on separate
pinned cores, each on its own fresh copy of the database and its own Redis
database. Pages behind the dashboard caches were measured warm, as a user who
reloads them sees them; the cold builds are in §4.

| Measure (HTTP 200, 165 pairs) | Baseline | Release | Change |
|---|---:|---:|---:|
| p50 | 2,123 ms | 1,895 ms | −10.7 % |
| p95 | 5,647 ms | 4,602 ms | −18.5 % |
| p99 | 8,035 ms | 5,619 ms | −30.1 % |
| Sum of medians | 408.4 s | 349.7 s | −14.4 % |
| Queries | 15,232 | 5,274 | −65 % |
| Status changes | — | 0 | — |
| Pairs ≥ 90 % faster / ≥ 50 % faster / > 15 % slower | — | 4 / 17 / 4 | — |
| Pairs still over 1 s / over 3 s | 165 / — | 129 / 44 | — |

**Against the 90 % target.** Met for `/projects/my-plan` (−92 to −93 % for
every role). The other fixed pages improved 43–87 % (`/leave/approvals`
−81 to −87 %, `/target-distribution` −75 %, `/admin-ops/team-plans` −61 %,
`/core-schools-oversight/` −58 to −62 %, `/budgets/overview` −43 to −48 %,
`/team-targets/matrix` −32 to −44 %, CD drilldown −28 to −34 %). The
country-wide oversight, SSA and targets pages that were not rebuilt (F-E) are
within noise of the baseline. **The 90 % reduction is therefore not met for
the cohort as a whole, and it is not claimed.** The four "slower" pairs are
single-sample noise on unchanged pages with unchanged query counts.

<details><summary>Every cohort pair (before → after, median of 3)</summary>

| Role | Route | Before ms | After ms | Δ % | Queries | KiB |
|---|---|---:|---:|---:|---|---|
| ia | `/core-schools-oversight/` | 8,201 | 3,159 | 61 | 46 → 36 | 2345 → 2345 |
| rvp | `/core-schools-oversight/` | 8,035 | 3,071 | 62 | 37 → 42 | 2340 → 2340 |
| regional_lead | `/core-schools-oversight/` | 7,873 | 3,182 | 60 | 37 → 32 | 2319 → 2319 |
| cd | `/core-schools-oversight/` | 7,690 | 3,196 | 58 | 38 → 36 | 2364 → 2364 |
| admin | `/core-schools-oversight/` | 7,444 | 3,103 | 58 | 34 → 51 | 2444 → 2444 |
| admin | `/team-planning-oversight/` | 5,733 | 5,555 | 3 | 32 → 32 | 1743 → 1743 |
| accountant | `/team-planning-oversight/` | 5,666 | 5,417 | 4 | 32 → 32 | 1617 → 1617 |
| ia | `/team-planning-oversight/` | 5,664 | 5,672 | -0 | 32 → 32 | 1643 → 1643 |
| rvp | `/team-planning-oversight/` | 5,647 | 5,619 | 1 | 42 → 44 | 1633 → 1633 |
| cd | `/team-planning-oversight/` | 5,454 | 5,354 | 2 | 42 → 42 | 1663 → 1663 |
| regional_lead | `/team-planning-oversight/export` | 4,872 | 4,684 | 4 | 11 → 11 | 0 → 0 |
| rvp | `/country-planning-oversight/export` | 4,817 | 4,689 | 3 | 7 → 7 | 0 → 0 |
| cd | `/work-plan/export.xlsx` | 4,782 | 3,733 | 22 | 27 → 27 | 237 → 237 |
| rvp | `/country-planning-oversight/` | 4,692 | 4,325 | 8 | 17 → 11 | 247 → 247 |
| admin | `/work-plan/export.xlsx` | 4,669 | 4,115 | 12 | 15 → 15 | 237 → 237 |
| cd | `/country-planning-oversight/export` | 4,627 | 4,640 | -0 | 7 → 7 | 0 → 0 |
| ia | `/country-planning-oversight/export` | 4,609 | 4,602 | 0 | 17 → 17 | 0 → 0 |
| admin | `/country-planning-oversight/export` | 4,548 | 4,323 | 5 | 7 → 7 | 0 → 0 |
| regional_lead | `/team-planning-oversight/` | 4,496 | 4,499 | -0 | 25 → 20 | 609 → 609 |
| ia | `/country-planning-oversight/` | 4,464 | 4,420 | 1 | 27 → 27 | 252 → 252 |
| admin | `/country-planning-oversight/` | 4,460 | 4,272 | 4 | 17 → 17 | 369 → 369 |
| accountant | `/work-plan/export.xlsx` | 4,386 | 3,656 | 17 | 15 → 15 | 237 → 237 |
| rvp | `/work-plan/export.xlsx` | 4,352 | 4,227 | 3 | 18 → 18 | 237 → 237 |
| cd | `/country-planning-oversight/` | 4,301 | 4,386 | -2 | 17 → 17 | 289 → 289 |
| admin | `/projects/my-plan` | 4,088 | 317 | 92 | 13 → 13 | 259 → 259 |
| ia | `/projects/my-plan` | 4,050 | 331 | 92 | 15 → 15 | 161 → 161 |
| cd | `/projects/my-plan` | 4,049 | 286 | 93 | 15 → 15 | 179 → 179 |
| coordinator | `/projects/my-plan` | 4,025 | 304 | 92 | 26 → 16 | 144 → 144 |
| cd | `/team-planning-oversight/export` | 3,957 | 3,925 | 1 | 20 → 20 | 0 → 0 |
| accountant | `/team-planning-oversight/export` | 3,936 | 3,633 | 8 | 10 → 10 | 0 → 0 |
| admin | `/team-planning-oversight/export` | 3,833 | 3,587 | 6 | 10 → 10 | 0 → 0 |
| ia | `/team-planning-oversight/export` | 3,707 | 3,929 | -6 | 10 → 10 | 0 → 0 |
| rvp | `/team-planning-oversight/export` | 3,676 | 3,768 | -3 | 20 → 20 | 0 → 0 |
| rvp | `/ssa` | 3,262 | 3,113 | 5 | 60 → 16 | 280 → 280 |
| regional_lead | `/team-targets/` | 3,196 | 2,962 | 7 | 58 → 48 | 173 → 173 |
| regional_lead | `/team-targets` | 3,190 | 2,906 | 9 | 48 → 48 | 173 → 173 |
| ia | `/ssa` | 3,172 | 2,981 | 6 | 15 → 15 | 299 → 299 |
| regional_lead | `/ssa` | 3,154 | 3,350 | -6 | 21 → 26 | 261 → 261 |
| cd | `/team-targets/recovery` | 3,110 | 2,820 | 9 | 69 → 47 | 4 → 4 |
| regional_lead | `/team-targets/recovery` | 3,103 | 2,941 | 5 | 64 → 51 | 4 → 4 |
| bt | `/ssa` | 3,086 | 2,963 | 4 | 13 → 13 | 249 → 249 |
| cd | `/analytics/country-director/drilldown` | 3,085 | 2,212 | 28 | 338 → 183 | 9 → 9 |
| cd | `/team-targets/` | 3,051 | 2,978 | 2 | 46 → 46 | 217 → 217 |
| admin | `/team-targets` | 3,026 | 3,161 | -4 | 43 → 43 | 297 → 297 |
| regional_lead | `/team-targets/export` | 3,025 | 3,103 | -3 | 48 → 48 | 0 → 0 |
| accountant | `/work-plan/` | 3,003 | 3,019 | -1 | 15 → 15 | 162 → 162 |
| admin | `/analytics/country-director/drilldown` | 2,974 | 1,974 | 34 | 331 → 186 | 9 → 9 |
| admin | `/work-plan/` | 2,969 | 3,151 | -6 | 20 → 15 | 283 → 283 |
| admin | `/team-targets/export` | 2,960 | 3,008 | -2 | 43 → 45 | 0 → 0 |
| cd | `/work-plan` | 2,954 | 2,984 | -1 | 39 → 34 | 203 → 203 |
| cd | `/ssa` | 2,945 | 2,942 | 0 | 25 → 20 | 310 → 310 |
| cd | `/work-plan/` | 2,925 | 2,869 | 2 | 24 → 19 | 203 → 203 |
| admin | `/ssa` | 2,923 | 3,200 | -9 | 30 → 18 | 391 → 391 |
| cd | `/ia/learning/` | 2,915 | 2,768 | 5 | 11 → 11 | 180 → 180 |
| accountant | `/ssa` | 2,915 | 2,982 | -2 | 13 → 13 | 267 → 267 |
| cd | `/team-targets/export` | 2,885 | 3,072 | -6 | 63 → 46 | 0 → 0 |
| admin | `/work-plan` | 2,881 | 3,011 | -4 | 20 → 15 | 283 → 283 |
| ia | `/ia/learning/` | 2,876 | 2,840 | 1 | 11 → 11 | 162 → 162 |
| admin | `/team-targets/recovery` | 2,829 | 3,005 | -6 | 49 → 44 | 4 → 4 |
| cd | `/team-targets` | 2,814 | 3,000 | -7 | 46 → 46 | 217 → 217 |
| rvp | `/work-plan/` | 2,749 | 3,072 | -12 | 18 → 18 | 177 → 177 |
| accountant | `/work-plan` | 2,747 | 2,895 | -5 | 15 → 15 | 162 → 162 |
| rvp | `/work-plan` | 2,710 | 3,055 | -13 | 18 → 28 | 177 → 177 |
| admin | `/team-targets/` | 2,708 | 3,120 | -15 | 43 → 43 | 298 → 298 |
| accountant | `/accounts/batch-payments` | 2,688 | 2,716 | -1 | 10 → 10 | 9353 → 9353 |
| admin | `/ia/learning/` | 2,688 | 2,639 | 2 | 9 → 9 | 260 → 260 |
| admin | `/accounts/batch-payments/` | 2,681 | 2,763 | -3 | 10 → 5 | 9473 → 9473 |
| accountant | `/accounts/advances` | 2,642 | 2,676 | -1 | 6 → 6 | 161 → 161 |
| admin | `/accounts/batch-payments` | 2,639 | 2,701 | -2 | 10 → 5 | 9473 → 9473 |
| accountant | `/accounts/batch-payments/` | 2,614 | 2,720 | -4 | 10 → 10 | 9353 → 9353 |
| admin | `/ssa/unmatched` | 2,554 | 2,484 | 3 | 6 → 11 | 4153 → 4153 |
| ia | `/ssa/unmatched` | 2,483 | 2,275 | 8 | 8 → 15 | 4058 → 4058 |
| admin | `/accounts/advances` | 2,462 | 2,487 | -1 | 12 → 12 | 281 → 281 |
| admin | `/accounts/advances/` | 2,447 | 2,456 | -0 | 6 → 6 | 281 → 281 |
| accountant | `/accounts/advances/` | 2,413 | 2,380 | 1 | 12 → 12 | 161 → 161 |
| ia | `/core-schools` | 2,322 | 2,296 | 1 | 78 → 81 | 374 → 374 |
| admin | `/clusters` | 2,274 | 2,034 | 11 | 21 → 21 | 493 → 493 |
| cd | `/clusters` | 2,228 | 2,446 | -10 | 23 → 23 | 413 → 413 |
| cd | `/core-schools` | 2,172 | 2,026 | 7 | 81 → 81 | 392 → 392 |
| cd | `/budgets/overview` | 2,163 | 1,120 | 48 | 74 → 32 | 171 → 171 |
| cd | `/cluster-oversight/` | 2,143 | 2,299 | -7 | 42 → 44 | 3441 → 3441 |
| ia | `/clusters` | 2,128 | 2,392 | -12 | 23 → 23 | 395 → 395 |
| ia | `/cluster-oversight/` | 2,123 | 2,111 | 1 | 47 → 42 | 3423 → 3423 |
| rvp | `/cluster-oversight/` | 2,105 | 1,966 | 7 | 43 → 43 | 3234 → 3234 |
| admin | `/cluster-oversight/` | 2,078 | 2,024 | 3 | 45 → 45 | 3521 → 3521 |
| admin | `/calendar` | 2,070 | 1,895 | 8 | 10 → 10 | 5521 → 5521 |
| accountant | `/cluster-oversight/` | 2,068 | 2,094 | -1 | 40 → 40 | 3218 → 3218 |
| rvp | `/budgets/overview` | 2,058 | 1,078 | 48 | 74 → 26 | 148 → 148 |
| accountant | `/budgets/overview` | 2,049 | 1,165 | 43 | 74 → 26 | 132 → 132 |
| ia | `/budgets/overview` | 2,019 | 1,081 | 46 | 68 → 32 | 153 → 153 |
| admin | `/core-schools` | 2,014 | 2,005 | 0 | 79 → 79 | 472 → 472 |
| accountant | `/analytics/export` | 1,937 | 1,878 | 3 | 49 → 49 | 0 → 0 |
| admin | `/team-targets/matrix` | 1,930 | 1,076 | 44 | 764 → 13 | 8 → 8 |
| admin | `/budgets/overview` | 1,914 | 1,099 | 43 | 74 → 26 | 251 → 251 |
| accountant | `/core-schools` | 1,868 | 1,846 | 1 | 74 → 79 | 336 → 336 |
| regional_lead | `/team-targets/matrix` | 1,831 | 1,242 | 32 | 768 → 18 | 8 → 8 |
| ia | `/analytics/export` | 1,817 | 1,741 | 4 | 51 → 51 | 0 → 0 |
| cd | `/analytics/export` | 1,808 | 1,810 | -0 | 51 → 51 | 0 → 0 |
| cd | `/team-targets/matrix` | 1,798 | 1,138 | 37 | 764 → 13 | 8 → 8 |
| admin | `/declining-schools` | 1,796 | 1,690 | 6 | 15 → 15 | 260 → 260 |
| ia | `/planning` | 1,793 | 1,778 | 1 | 121 → 121 | 264 → 264 |
| cd | `/planning` | 1,782 | 1,752 | 2 | 121 → 121 | 282 → 282 |
| cd | `/declining-schools` | 1,756 | 1,706 | 3 | 17 → 17 | 180 → 180 |
| ia | `/declining-schools` | 1,725 | 1,638 | 5 | 17 → 12 | 169 → 169 |
| rvp | `/declining-schools` | 1,705 | 1,730 | -1 | 18 → 18 | 154 → 154 |
| accountant | `/planning` | 1,675 | 1,534 | 8 | 114 → 114 | 240 → 240 |
| cd | `/loans/export.xlsx` | 1,633 | 1,626 | 0 | 10 → 10 | 269 → 269 |
| ia | `/loans/export.xlsx` | 1,616 | 1,431 | 11 | 10 → 10 | 269 → 269 |
| admin | `/planning` | 1,570 | 1,539 | 2 | 114 → 114 | 362 → 362 |
| ia | `/analytics/verification-quality` | 1,535 | 1,347 | 12 | 50 → 50 | 322 → 322 |
| pl | `/cluster-oversight/` | 1,466 | 1,504 | -3 | 55 → 55 | 1634 → 1634 |
| ia | `/country-budget/plan-sources` | 1,432 | 1,266 | 12 | 13 → 13 | 15 → 15 |
| bt | `/loans/export.xlsx` | 1,429 | 1,750 | -22 | 8 → 8 | 269 → 269 |
| rvp | `/loans/export.xlsx` | 1,423 | 1,413 | 1 | 11 → 11 | 269 → 269 |
| rvp | `/country-budget/plan-sources` | 1,395 | 1,288 | 8 | 13 → 7 | 15 → 15 |
| ia | `/ia/dashboard/` | 1,375 | 1,260 | 8 | 27 → 27 | 279 → 279 |
| regional_lead | `/analytics/export` | 1,338 | 1,292 | 3 | 50 → 50 | 0 → 0 |
| cd | `/ia/dashboard/` | 1,333 | 1,388 | -4 | 25 → 25 | 296 → 296 |
| admin | `/country-budget/plan-sources` | 1,316 | 1,282 | 3 | 13 → 13 | 15 → 15 |
| cd | `/country-budget/plan-sources` | 1,271 | 1,235 | 3 | 13 → 13 | 15 → 15 |
| cd | `/leave/approvals` | 1,247 | 235 | 81 | 1175 → 134 | 247 → 247 |
| admin | `/ia/dashboard/` | 1,217 | 1,115 | 8 | 23 → 23 | 376 → 376 |
| cd | `/leave/approvals/` | 1,212 | 233 | 81 | 1175 → 134 | 247 → 247 |
| accountant | `/country-budget/plan-sources` | 1,156 | 1,133 | 2 | 7 → 7 | 15 → 15 |
| bt | `/ssa/export` | 1,154 | 1,004 | 13 | 8 → 8 | 1932 → 1932 |
| cd | `/schools` | 1,120 | 1,168 | -4 | 33 → 38 | 591 → 591 |
| ia | `/analytics/visit-effectiveness` | 1,113 | 1,007 | 10 | 11 → 11 | 169 → 169 |
| cd | `/analytics/visit-effectiveness` | 1,109 | 1,031 | 7 | 12 → 12 | 180 → 180 |
| ia | `/schools` | 1,109 | 1,166 | -5 | 34 → 39 | 609 → 609 |
| pl | `/leave/approvals/` | 1,097 | 166 | 85 | 1125 → 84 | 208 → 208 |
| admin | `/schools` | 1,092 | 1,222 | -12 | 32 → 37 | 698 → 698 |
| cd | `/analytics/verification-quality` | 1,090 | 1,117 | -2 | 47 → 52 | 331 → 331 |
| admin | `/admin-ops/team-plans` | 1,079 | 420 | 61 | 655 → 11 | 266 → 266 |
| pl | `/leave/approvals` | 1,077 | 168 | 84 | 1125 → 84 | 208 → 208 |
| pl | `/core-schools-oversight/` | 1,054 | 550 | 48 | 35 → 35 | 860 → 860 |
| admin | `/analytics/export` | 1,042 | 923 | 11 | 47 → 47 | 0 → 0 |
| rvp | `/leave/approvals/` | 1,034 | 132 | 87 | 1098 → 57 | 182 → 182 |
| accountant | `/budget/` | 1,020 | 1,037 | -2 | 42 → 42 | 135 → 135 |
| rvp | `/analytics/visit-effectiveness` | 1,002 | 904 | 10 | 12 → 12 | 155 → 155 |
| pl | `/team-planning-oversight/` | 994 | 1,022 | -3 | 44 → 44 | 2824 → 2824 |
| admin | `/analytics/visit-effectiveness` | 989 | 979 | 1 | 8 → 8 | 260 → 260 |
| ia | `/budget/` | 969 | 915 | 6 | 42 → 42 | 157 → 157 |
| rvp | `/leave/approvals` | 967 | 128 | 87 | 1098 → 57 | 182 → 182 |
| ia | `/target-distribution` | 962 | 237 | 75 | 179 → 14 | 156 → 156 |
| ia | `/ssa/export` | 954 | 958 | -0 | 10 → 10 | 1932 → 1932 |
| cd | `/budget` | 948 | 952 | -0 | 47 → 42 | 176 → 176 |
| cd | `/budget/` | 946 | 1,177 | -24 | 42 → 42 | 176 → 176 |
| admin | `/budget` | 905 | 929 | -3 | 40 → 45 | 255 → 255 |
| admin | `/budget/` | 850 | 1,002 | -18 | 40 → 40 | 255 → 255 |
| pl | `/analytics/export` | 821 | 931 | -13 | 55 → 55 | 0 → 0 |
| admin | `/leave/calendar` | 765 | 880 | -15 | 7 → 7 | 2645 → 2645 |
| admin | `/clusters/schedule-training-drawer` | 738 | 724 | 2 | 27 → 27 | 204 → 204 |
| admin | `/pl/review-queue` | 663 | 690 | -4 | 6 → 6 | 259 → 259 |
| ia | `/analytics/` | 614 | 556 | 10 | 12 → 12 | 695 → 695 |
| cd | `/analytics/` | 586 | 599 | -2 | 14 → 14 | 714 → 714 |
| accountant | `/analytics/` | 582 | 592 | -2 | 10 → 10 | 670 → 670 |
| regional_lead | `/analytics/` | 578 | 591 | -2 | 13 → 13 | 664 → 664 |
| cd | `/analytics` | 576 | 577 | -0 | 14 → 14 | 714 → 714 |
| admin | `/analytics` | 569 | 530 | 7 | 10 → 10 | 794 → 794 |
| accountant | `/analytics` | 566 | 585 | -3 | 10 → 10 | 670 → 670 |
| ia | `/analytics` | 554 | 542 | 2 | 12 → 12 | 695 → 695 |
| pl | `/analytics/` | 540 | 580 | -7 | 19 → 19 | 607 → 607 |
| admin | `/analytics/` | 538 | 517 | 4 | 10 → 10 | 794 → 794 |
| regional_lead | `/analytics` | 537 | 541 | -1 | 13 → 13 | 664 → 664 |
| cd | `/analytics/country-director` | 166 | 148 | 10 | 8 → 8 | 481 → 481 |

</details>


## 7. Concurrency results (23, 24)

**Environment (never production).** Server: `config.settings.loadtest`
(`DEBUG=False`), gunicorn + `UvicornWorker`, **2 workers pinned to one CPU**,
admission guard 6 per worker, **no Redis** (per-worker LocMem, database
sessions), `CONN_MAX_AGE=0`, `MALLOC_ARENA_MAX=2` — the production web
service's shape (`apps-s-1vcpu-1gb-fixed`, `WEB_CONCURRENCY=2`, `REDIS_URL`
unset). Client on the other three CPUs. Each build ran on its own fresh copy
of the 50,000-school database, one after the other.

**Workload.** `scripts/load_test.py --mix spec50`: the approved 50-user role
mix (CCEO 18, PL 8, IA 5, partner 4, accountant 3, HR 3, BT 3, MFI 3, CD 2,
RVP 1), one real session per user, 3–12 s think time, full pages, HTMX
search and paging, and governed writes (evidence upload, PL confirmation, IA
verification, 10 % of decisions sent twice at once) with an integrity check.
Stages: 10 users 60 s, **50 users 480 s**, 100 users 120 s, 150 users 90 s,
200 users 90 s, then 60 s at one user.

| Stage | Build | Requests | req/s | p50 ms | p95 ms | p99 ms | 503 | Error % | Peak RSS MB | CPU % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 users | baseline | 80 | 1.33 | 258 | 1,344 | 2,982 | 0 | 0.00 | 892 | 28.5 |
| | release | 80 | 1.33 | 257 | 1,152 | 3,095 | 0 | 0.00 | 839 | 28.8 |
| **50 users** | baseline | 1,594 | 3.32 | 4,866 | 18,076 | 29,655 | 6 | 1.38 | 1,670 | 92.7 |
| | release | 1,654 | 3.45 | 4,382 | 17,755 | 27,230 | 4 | 0.91 | 1,773 | 93.3 |
| 100 users | baseline | 679 | 5.66 | 5,292 | 24,290 | 30,030 | 358 | 55.96 | 1,880 | 98.3 |
| | release | 692 | 5.77 | 9,655 | 22,466 | 30,028 | 262 | 39.60 | 1,896 | 98.4 |
| 150 users | baseline | 1,027 | 11.41 | 834 | 23,351 | 30,028 | 814 | 80.62 | 2,045 | 98.8 |
| | release | 1,025 | 11.39 | 803 | 22,380 | 30,029 | 800 | 79.51 | 1,951 | 98.8 |
| 200 users | baseline | 1,527 | 16.97 | 852 | 22,498 | 30,003 | 1,260 | 83.56 | 2,002 | 98.8 |
| | release | 1,381 | 15.34 | 1,507 | 23,568 | 30,026 | 1,159 | 85.30 | 2,095 | 98.9 |
| recovery | baseline | 78 | 1.30 | 18,174 | 26,174 | 27,418 | 21 | 28.21 | 2,032 | 34.7 |
| | release | 99 | 1.65 | 18,543 | 30,030 | 30,031 | 54 | 62.63 | 2,045 | 46.9 |

**Integrity (both builds): passed.** Every accepted evidence upload, PL
confirmation and IA verification was applied exactly once and audited once;
no lost, unseen or duplicated transition, including the concurrent double
submissions; zero 5xx and zero transport failures on writes. Refused writes
were admission-guard 503s, which the client can retry.

**Reading it.** The single CPU is 93 % busy at 50 users in both builds, so
every request queues behind every other and the per-page gains in §4–§6
barely reach the load figures: at 50 users the release served 4 % more
requests with a 10 % lower p50, 2 % lower p95 and a third fewer refusals; at
100 users it refused 30 % fewer requests (its p50 is higher because more of
them were admitted and queued). Peak memory at 1.7–2.1 GB exceeds the 1 GiB
instance in both builds. Recovery after 200 users does not drain within 60 s
in either build (the release's recovery window is noisier). **The 50-user
gates are not met at production shape, and no code change measured here can
meet them on one vCPU**; the capacity change in §10 is the prerequisite, and
the stages must then be re-run there.

**Candidate capacity: 2 vCPU, 4 workers, Redis (release build at `dd1e36f`).**
The same workload and database, with the server pinned to two CPUs, four
workers, and a Redis database of its own as cache and session store (the
shape §10 proposes). Stages: 10 users 60 s, 50 users 300 s, 100 users 120 s,
150 users 90 s, then 60 s at one user. PostgreSQL shared the machine and was
not pinned, so its CPU also competed with the server's two cores.

| Stage | Requests | req/s | p50 ms | p95 ms | p99 ms | 503 | Error % | DB conns | Peak RSS MB | Web CPU % of 2 cores | DB CPU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 users | 80 | 1.33 | 250 | 1,160 | 3,297 | 0 | 0.0 | 4 | 1,274 | 16 | 3 |
| **50 users** | 1,580 | 5.27 | **767** | **5,700** | 11,946 | **0** | **0.0** | 22 | 2,535 | **67** | 38 |
| 100 users | 732 | 6.10 | 5,391 | 22,151 | 30,032 | 28 | 5.6 | 27 | 3,015 | 84 | 71 |
| 150 users | 657 | 7.30 | 12,204 | 24,472 | 30,034 | 130 | 23.0 | 27 | 3,505 | 87 | 70 |
| recovery | 104 | 1.73 | 14,484 | 24,076 | 30,033 | 3 | 4.8 | 28 | 3,402 | 26 | 20 |

Integrity passed again (evidence 25/25, PL confirmations 21/21 including
two concurrent double submissions, IA verifications 20/20; no lost, unseen
or duplicated transition; zero 5xx). At 50 users the p50 falls from 4.4 s
to 0.77 s and nothing is refused, so doubling the web tier removes most of
the queueing; but p95 is still 5.7 s, web CPU is 67 % (gate < 60 %), and the
tail is set by the heavy country pages (slowest p95 under load:
`/country-planning-oversight/`, `/core-schools`, `/ssa`,
`/analytics/verification-quality`, `/ia/dashboard/` at the 30 s timeout;
`/budget`, `/team-planning-oversight/`, `/analytics` 20–26 s), which hold a
worker for seconds each. Peak memory for four workers is 2.5 GB at 50 users
and 3.5 GB at 150. **Maximum stable concurrency at this shape: 50 users**
(zero refusals, but outside the latency gates); 100 users is past the knee.

**Not run:** the 2-hour sustained 50-user run, the 8-hour soak, and
stress-to-failure beyond 200 users. The maximum stable concurrency at
production shape is **below 50 users** for both builds (1 % refused, p95
18 s at 50); the first saturated resource is the web CPU; the database stayed
below 42 % CPU with 15–17 connections and no lock waits.


## 8. Tests, lint and security (26, 27)

| Check | Result |
|---|---|
| Full Django suite (`manage.py test --parallel 3 --exclude-tag=scale`, as CI) | 8,924 tests; the only failures were two generated manifests whose source line numbers moved (KPI inventory, traceability fingerprint). Regenerated with `build_kpi_inventory` / `build_traceability_matrix`; the traceability **payload hash is unchanged**, and the 64 manifest tests then pass |
| New tests | 7 (leave queue ×3, grouped budget rollups, matrix equivalence and flatness, Team Plans flatness, workbook bytes); the matrix and Team Plans tests were run against the previous code and fail there |
| Oversight oracle (frozen copy of the pre-change code) | 16/16 pass |
| `ruff check` / `ruff format --check` | clean |
| `makemigrations --check` | no changes |
| Bandit (`-r apps config -ll -ii`, as CI) | no issues |
| Browser suites (Playwright journeys, role route audit, visual) | not run in this session; CI runs *Browser Journeys & Role Route Audit* on the PR |

## 9. Findings recorded, not changed (parity lock)

Each of these changes what a user sees or when data is written, so under the
brief's parity lock it needs an owner decision.

| # | Finding | Evidence | Proposed correction |
|---|---|---|---|
| F-A | **Fixed after owner approval (see §5, R-2).** Admin Team Plans never showed a next action | — | — |
| F-B | **Fixed after owner approval (see §5, R-3).** Map metrics were not deterministic | — | — |
| F-C | **Fixed after owner approval (see §5, R-4).** The fiscal-year rollover ran inside a user request | — | — |
| F-D | **Fixed after owner approval (see §5, R-6).** Leadership pages rebuilt the achievement ledger on every load (write on read): Team Targets and CD analytics rebuild every officer's ledger (~2 s for 150 officers) | profile of `/team-targets/` | move the rebuild to the source workflows or a scheduled job; changes freshness |
| F-G | **Fixed after owner approval (see §5, R-5).** Core Schools lists had no total order. The main list orders by `-created_at` only (seeded and imported schools share timestamps) and the Attention Needed card lists plans in heap order, so the rows shown change between loads of the *baseline* (two baseline captures differ on 20 of 90 `/core-schools` responses, exactly as baseline vs release does) | baseline-vs-baseline capture | end both orderings with `id` (as F-9/F-11 did); a user may then see a different but stable first page |
| F-H | **`/core-schools` writes on read.** Every load of the page creates up to 100 missing core plans for the reader's scope (`self_heal_plans`), so what the Team Targets core-package gap shows depends on how many times someone has opened Core Schools | two database copies from one pristine copy: 0 → 800 and 0 → 600 plans after a day of page loads | create core plans when a school becomes core (the write path) or in a scheduled job, as R-6 did for the ledger; changes when plans appear |
| F-E | **Heavy country pages still take seconds.** Team and country planning oversight and their exports (4–6 s), SSA (≈3 s), IA learning (≈3 s), the Country Director's dashboard (2.7 MB of HTML, ≈8 s under load) for country roles at 50,000 schools; they build every item in the country in Python | profiles in §6 | per-lead lazy sections or read models, each needing a parity review |

### Proposals that needed approval

The 2026-09-24 order says: where an optimization cannot be completed without
a visible or behavioural change, stop, document the constraint, explain the
change, and do not implement it without approval. The owner approved all six
on 2026-09-25. P-3 (Brotli), P-4, P-5 and P-6 are implemented (§5, R-5 to R-9); P-1, P-2 and
P-3 are in progress and each will be verified against the page's final
rendered state before it is claimed.

| # | Gate it serves | Technical constraint | Proposed change | What would change for users | Expected result |
|---|---|---|---|---|---|
| P-1 | common route P95 ≤ 400 ms; analytics ≤ 2 s; load tail (§7) | `/country-planning-oversight/`, `/team-planning-oversight/` and exports, `/core-schools` KPIs, `/ssa`, `/analytics/verification-quality` and the IA portfolio build every activity, SSA score or domain pair in the country in Python on each request. Examples: 74,000 activities; 160,208 domain pairs; about 1.1 s of Python on `/core-schools` after F-16. No exact-parity rewrite of these loops reaches 400 ms. | Per-FY summary tables (read models), updated inside the same transactions that change their sources (activity status, SSA confirmation, cost lines), or rebuilt from the existing domain events. Pages read the summary. | Nothing visible if updated in-transaction, but those writes get slower. If updated from events, figures can lag a write by seconds. | Country pages bounded by the summary read: tens of ms instead of 2–6 s. This removes the 20–30 s tail under load. |
| P-2 | completed analytics ≤ 2 s or durable async | `/analytics`, `/ia/dashboard/` and the CD dashboard compute every panel before the first byte (CD dashboard cold TTFB 10–11 s in the browser run) | Render the page shell, then load each heavy panel as an HTMX fragment (`hx-trigger="load"`). The fragments are cached per scope, and the cache is invalidated by the same events. | The page paints first and panels fill in after it. A loading state appears where there was none. | Shell ≤ 500 ms; each panel within its own budget; no worker held for seconds. |
| P-3 | FCP ≤ 1.2 s, LCP ≤ 2 s (§11) | Every page blocks on 17 stylesheets plus fonts, about 1.8–2.5 MB cold. HTML, CSS and JS are byte-identical across builds, and so are FCP/LCP. | Serve the stylesheets as one concatenated file in the same cascade order and preload the fonts. Review the three parser-blocking head scripts (`htmx`, `chart-standard.js`, `alpine-components.js`); each can be deferred only where the order htmx → components → Alpine start is kept. Verify at 10 widths by pixel diff before release. | Intended to be none. It needs a full visual regression pass because cascade order and script timing can change rendering. | Cold FCP drops by the round trips saved (15+ requests at 150 ms RTT). The gate also needs HTTP/2 at the edge, which production's CDN provides and the local HTTP/1.1 server does not. |
| P-4 | CLS ≤ 0.05 | Layout shifts of 0.15–0.35 on the CCEO dashboard, planning, schools, team oversight and CD analytics, identical in both builds. They come from content that loads in after the first paint without reserved space. | Reserve the height of each late element (chart containers, KPI strips, HTMX-swapped panels) in CSS. | Blank space appears where content will land, instead of content moving. | CLS < 0.05 on the measured pages. |
| P-5 | DOM ≤ 3,000 nodes; fragment/page payload | `/team-planning-oversight/` ships 22,406 nodes and 2.8 MB of HTML (186 KB gzip); `/loans` 9,332 nodes; `/analytics` 8,670; the CD dashboard 5,238 | Paginate or lazily expand the long lists (for example, per-lead sections that load on open) | Lists start collapsed or paged | DOM and payload inside the limits |
| P-6 | F-D, F-G | See the table above | See the table above | Freshness of the achievement ledger (F-D); a stable first page (F-G) | Leadership pages lose the per-load rebuild (~2 s) |

## 10. Infrastructure (21)

The App Platform spec runs the web service as **one instance** of
`apps-s-1vcpu-1gb-fixed` with `WEB_CONCURRENCY=2` and no Redis
(`.do/app.yaml`). That is a single point of failure (21.2) and the capacity
ceiling measured in §7. No infrastructure was changed: resizing costs money
and is the owner's decision.

| Item | Finding |
|---|---|
| Exhausted resource | **Web CPU.** One vCPU is 93 % busy at 50 users in both builds (§7) while the database stays below 42 % CPU with 15–17 connections and no lock waits. Second: **web memory**. Two workers peak at 1.7–2.1 GB against a 1 GiB instance. |
| Required infrastructure | Web tier with at least 2 vCPU of dedicated CPU and 4 GB memory in total, as two instances behind the existing readiness check, plus a managed Redis (cache and sessions) before the second instance. With per-worker LocMem caches and database sessions, a second instance serves stale dashboard fragments; the spec's own comment explains this. |
| Configuration | Per instance: a dedicated-CPU size with 1 vCPU / 2 GB or larger, `WEB_CONCURRENCY=2`, `REDIS_URL` set to the managed Redis, the rest unchanged. Alternatively, one 2 vCPU / 4 GB instance with `WEB_CONCURRENCY=4`, which removes the queueing but not the single point of failure. |
| Expected cost | Not verifiable here: the provider's price list is blocked by this environment's network policy. The owner should price two dedicated-CPU instances of the size above plus the smallest managed Redis node from the current App Platform and Managed Databases price lists. |
| Expected result | Measured at the 2 vCPU / 4-worker / Redis shape (§7): 50 users with **p50 0.77 s** (was 4.4 s), **zero refusals** (was 0.9 %), p95 5.7 s, web CPU 67 %. So the capacity change is necessary. It is **not sufficient** for the p95 ≤ 400 ms gate: the tail is the heavy country pages (F-E), which need the read models in §9 whatever the size of the tier. |

## 11. Gates the brief requires that were not run here

| Gate | Status |
|---|---|
| 2-hour 50-user sustained test, 8-hour soak | not run (session time); §7 is a staged run |
| Fault injection (web instance, Redis, worker, scheduler, integrations, storage, DNS, DB connection) | not run — no staging |
| Backup restore, migration rehearsal, rollback rehearsal | not run — no staging (`scripts/backup_restore_rehearsal.sh`, `scripts/rollback_rehearsal.sh` exist) |
| Canary, production smoke | not run — no production access |
| Browser-measured FCP/LCP/INP/CLS and 100-navigation chart memory | not run in this session |
| Screenshot visual regression at the 10 breakpoints × themes | not run; replaced for this change by byte-identical HTML with no template/CSS/JS change (§3) |

## 12. Release decision

**NO-GO: The optimized release has failed one or more mandatory gates and is
not authorized for production rollout.**

| Failed gate | Route or workflow | Baseline | Final | Risk | Required correction | Required retest |
|---|---|---|---|---|---|---|
| Common-page P95 ≤ 500 ms / heavy analytics ≤ 2.5 s | country-role oversight, analytics and exports (F-E) | cohort p95 5,647 ms | cohort p95 4,602 ms | slow pages for leadership roles | F-E work, each with a parity review | cohort re-timing (§6 method) |
| 50/100/150/200-user load at production shape | whole platform | 50 users: p95 18.1 s, 1.38 % refused | 50 users: p95 17.8 s, 0.91 % refused | queueing and failed requests at peak on one vCPU | the §10 capacity change | `scripts/load_test.py --mix spec50` on the resized staging service, then a 2-hour sustained run and an 8-hour soak |
| Single point of failure | web service | 1 instance | 1 instance | outage on any restart or instance loss | §10 | failover drill |
| Staging, restore, rollback, canary, smoke | release process | not run | not run | unrehearsed recovery | run the repository's rehearsal scripts against staging | rehearsal logs, smoke report |

What this branch is safe to do now: merge and deploy as an improvement. It
changes no template, style, script, route, permission, workflow state,
calculation or export definition; its one migration only widens a column; and
rolling back is redeploying the previous image.
