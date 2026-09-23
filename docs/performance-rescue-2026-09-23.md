# Performance Rescue, Concurrency and Freeze Elimination — 2026-09-23

Branch `claude/determined-bell-sg96zv`, PR #121. Code measured and released as
of 98dc442; this report is committed on top of it. Every figure below was
measured on an isolated, production-shaped local environment. No load, stress
or write test touched production.

Reports 26.1–26.8 follow in order. §10 is the acceptance checklist and the
release decision.

## 1. Executive Report (26.1)

**What was wrong.** At production's shape, the platform froze at ordinary
use: one vCPU, two Uvicorn workers, no shared cache, 16k schools. With 25
concurrent users, p95 was 20.6 s, and 30 s timeouts appeared. At 50 users
(2× the assumed peak), 30% of requests failed.

The causes were measured, not guessed. Each was a request doing far more work
than its page needed:
- PostgreSQL JIT spent 4.7 s compiling a 76 ms query.
- A Core Schools GET wrote ~550 rows one at a time.
- Scope sets of up to 16,000 ids were bound as literal parameters.
- Whole querysets were evaluated to test for emptiness.
- An accidental 39.8-million-lookup loop.
- Every HTMX swap redrew every chart in the browser.

A second group of defects makes a slowdown turn into a stall:
- stampede waiters rebuilding the same snapshot;
- scheduler threads stuck on dead database connections;
- a 1 s misfire grace dropping daily jobs;
- two workers outgrowing the 1 GiB instance.

**What changed.**
- 20 freeze causes registered (§2). 18 are fixed or reduced, each re-measured and pinned by a
  test; the rest are open, with the evidence and a design.
- Request timing is now visible in production:
  - a `Server-Timing` header;
  - a PII-free slow-request log;
  - a per-route p50/p95/p99 report with alerting checks in System Health.
- Scheduler and cache resilience fixes.
- A security fix to the login rate limit's client address (§7.6).
- One proven-dead module removed; the rest of the legacy inventory classified
  with evidence.

**Result, same environment, before → after.**

| | 25 users (expected peak) | 50 users (2× peak) | 100 users |
|---|---|---|---|
| p50 | 4.4 s → **0.69 s** | 20.1 s → **4.9 s** | — |
| p95 | 20.6 s → **5.9 s** | 30.0 s → **13.5 s** | 26.3 s → 21.2 s |
| Errors | 3.25% → **0.81%** | 30.2% → **0.31%** | 73.6% → 43.7% (shed as 503) |
| Peak memory (RSS) | 1.50 → 1.04 GB | 1.82 → 1.38 GB | 1.98 → 1.56 GB |

**What this does not prove.** On the current single vCPU, the platform is
**not** reliably fast at 2× expected peak: p95 is 13.5 s at 50 users. The CPU
is saturated from the 25-user stage on, and two workers use more memory than
the 1 GiB instance has. Removing request cost moved the cliff; it did not
remove it. §7.3 sizes the capacity change from a measured run on a
scaled-out shape: 2 vCPU, 4 workers and shared Redis. With this code, 50 users
ran at p50 0.58 s, p95 4.2 s and 0.19% errors.

**Decision** (§10):
- **GO** to deploy this release once CI is green. It is a measured improvement that changes no business rule.
- **NO-GO** on declaring the platform ready for 2× expected peak on the current 1 vCPU / 1 GiB web instance. That needs the capacity change in §7.3 and a rerun of the 50/100-user stages on it.

## 2. Freeze Register (26.2)

Every entry was reproduced before it was fixed, and each fix was re-measured on
the same data. "Scaled" means `edify_scale_*`: the seed estate grown to 16,274
schools, 23,620 FY activities and production's shape (one CPU, two Uvicorn
workers, admission guard at 6, no Redis, `CONN_MAX_AGE=0`).

| # | Symptom a user sees | Root cause (evidence) | Fix | Before → after (evidence) | Status |
|---|---|---|---|---|---|
| F1 | Whole app stops answering for 5–30 s under ordinary use | Single CPU saturated by request CPU; every worker slot held by slow pages; guard queue fills, then 503s | F2–F12 below; capacity recommendation in §7 | 25 users: p95 20.6 s → 5.9 s, errors 3.25% → 0.81%; 50 users: errors 30.2% → 0.31% | Improved, **not** fixed at production size (§3) |
| F2 | Lending/finance KPI pages take seconds on first view | PostgreSQL JIT compiling large ORM plans: 4.7 s compile, 76 ms execute | `-c jit=off` (web tier), `ALTER ROLE … SET jit='off'` for pooled sessions, readiness reports `db_jit` | 4.7 s → 0.08 s | Fixed, test-pinned |
| F3 | Core Schools page slow and writes on every view | GET self-heal wrote ~550 rows one at a time per load | Bounded bulk heal (`bulk_create` with conflict handling, 1-by-1 fallback on `IntegrityError`); SSA gate in the query | ~550 single-row writes → a fixed handful of statements (≤10, test-pinned) | Fixed, 5 tests |
| F4 | SSA workspace (CD) ~11 s | `safe_mean` via pandas per call; scope bound as a 16k-parameter literal `IN`; score ids as literal list | Float fast path (numerically identical on 60,004 random cases); scope as subquery; ids as one array parameter | 10.8 s → 1.9 s | Fixed |
| F5 | Planning (CD) 3.6 s | Organisation-wide id sets materialised in Python and re-bound as literals | Subqueries, ids-only KPI loop, NULL-safe `NOT IN` | 3.6 s → 1.0 s | Fixed, query count pinned |
| F6 | Team targets (regional) 4.5 s | A set rebuilt inside a comprehension: 39.8 M dict lookups | Build once per member; narrow reads | 4.5 s → 1.8 s | Fixed |
| F7 | CD/RVP dashboards, team targets | Ledger rebuild instantiated full models per source row | Named tuples, needed columns only | ~7× less CPU, identical ledger | Fixed |
| F8 | PL dashboard past-due tables 1.5 s | Every past-due row built (names, reminders, amounts) to show 10 | Lazy `Sequence`; rows built only for the page shown | 1.5 s → 60 ms warm | Fixed |
| F9 | Many scoped pages fetch everything to test emptiness | `queryset or Model.objects.none()` evaluates the queryset (8 sites) | `scoping.or_empty` | Whole-scope fetch → none | Fixed |
| F10 | My Plan N+1 | `COUNT` per cluster row | One grouped count | N queries → 1 | Fixed |
| F11 | Page "hangs" for ~0.3 s per chart after opening a drawer, paging a table or typing in search | Every HTMX swap dispatched `edify-theme-change`, which redraws every chart | Dispatch removed; real theme switch still redraws | 2 redraws (~330 ms main thread) → 0 per swap on /ssa | Fixed, e2e spec fails on old code |
| F12 | Tab gets slower the longer it is used (HR map/ops cycling) | Swapped-out chart panels retained by window listeners and a ResizeObserver | Chart wrappers registered with the sweep; observer unobserves detached SVGs; map component `destroy()` | ~7,500 → ~4,000 detached nodes per cycle | Improved; residual R4 |
| F13 | Real users queue behind speculative prefetches | Speculation rules prefetched analytics views on 200 ms hover and the guard queued them | Conservative eagerness; guard refuses prefetch when no slot is free | Prefetch never waits for a slot | Fixed, 2 tests |
| F14 | Link-heavy pages spend time resolving URLs | Link gating resolved every drawn link against ~1,300 patterns, twice per link | Per-URLconf LRU; resolve once per link | PL team oversight 2,465 → 2,360 ms median | Fixed |
| F15 | Scheduled work silently stops after a database blip | Scheduler pool threads never retire connections; a dropped connection fails every later job on that thread | Retire unusable connections before/after each tracked job (outside transactions) | Proven by a test that kills the backend | Fixed, test |
| F16 | Daily jobs silently skipped on a busy minute or a deploy | APScheduler default misfire grace is 1 s | 300 s grace, coalesce, one instance per job | — | Fixed, test |
| F17 | Web instance restarts under load (looks like a freeze, loses in-flight work) | Two workers exceed the 1 GiB instance: 1.04 GB RSS at 25 users, 1.38 GB at 50 (after the fixes) | Arena cap (F20) plus the capacity change in §7.3 | §3.4 | Open: capacity decision |
| F18 | A slow dashboard gets slower the more people open it at once | Cache stampede: waiters gave up after 3 s and rebuilt the same ≥3 s snapshot themselves, each on the one CPU | Waiters wait for the lock owner's answer (bounded by the lock TTL) | Duplicate rebuilds → one per snapshot | Fixed, 3 tests |
| F19 | IA and accountants see the closure queue take ~25 s under load | Queue re-derives every stale checklist on GET: ~1,000 statements with ~370 writes per view, repeated by each concurrent viewer | Recorded with design (scheduled refresh, read-only GET) | 4.2 s single / 25 s p50 under load | **Open (R10)** |
| F20 | Memory grows under sustained load until the instance restarts | glibc per-thread malloc arenas in thread-per-request workers | `MALLOC_ARENA_MAX=2` in the image | Peak RSS growth 1.04 → 1.66 GB replaced by a 1.08–1.13 GB plateau | Fixed in image; capacity still short (F17) |

## 3. Load-Test Report (26.3)

### 3.1 Environment (never production)

| Item | Setting | Why |
|---|---|---|
| Data | `edify_scale_pristine`: the seed estate grown with `scripts/scale_local_dataset.py` to 16,274 schools, 2,577 clusters and 23,620 live FY activities, with their SSA records, ledgers and assignments | Production-shaped volumes. Every run starts from a fresh copy |
| Web | `config.settings.loadtest` (`DEBUG=False`); gunicorn + `UvicornWorker`, 2 workers, `--timeout 60`, pinned to **one CPU** | Production web service: `apps-s-1vcpu-1gb-fixed`, `WEB_CONCURRENCY=2` |
| Guard | `WEB_MAX_CONCURRENT_REQUESTS=6` per worker | Production default |
| Cache | No Redis (per-worker LocMem) unless a run says otherwise | Production has `REDIS_URL` unset |
| Database | PostgreSQL 16, `CONN_MAX_AGE=0` | Production direct connection |
| Client | `scripts/load_test.py`, pinned to other CPUs so it cannot take the server's | — |

### 3.2 Workload

- **Sessions and journeys.** Each virtual user is one real account with its
  own session and keep-alive connection. It walks a weighted journey for its
  role:
  - full pages;
  - HTMX partial refreshes (search, pagination);
  - a school's detail page;
  - a harmless CSRF-protected write.
- **Think time.** 3–12 s between steps. A keep-alive socket that idled past
  uvicorn's 5 s is retried once, as a browser does.
- **Role mix.** CCEO 45, PL 12, IA 7, partner 6, accountant 5, coordinator 4,
  HR 4, CD 3, BT 3, MFI 3, RVP 2, regional lead 2.
- **Stages.** Users ramp in over the first fifth of each stage. The stage
  then holds its user count for the stated seconds. A 30 s recovery follows
  with one user, to see whether the queue drains.
- **Timeouts and errors.** The client timeout is 30 s. Timeouts,
  transport errors and 5xx (including the guard's 503) count as errors.
- **Monitor.** Every 2 s it samples:
  - Postgres connections by state, and lock waiters;
  - server RSS summed over all gunicorn processes;
  - server CPU.

**Expected peak (assumption).** This programme had no production traffic
data. The expected peak is taken as **25 concurrent active users**: the field
team in one morning planning window. **2× expected peak is 50 users**, and the
100-user stage is headroom. At production's shape the 100-user stage already
sheds most requests. The 250-user stage was therefore run only on the
scaled-out shape (§3.4), where the answer is informative. 500 was not run:
§3.4 shows why it would only measure the refusal path.

### 3.3 Results at production's shape (1 CPU, 2 workers, no Redis)

Same data, same harness, same pinning; stages of 90 s (100u: 60–90 s).
Latency in ms, client-side, including queue time. RSS is summed over the
gunicorn processes; it overstates real use by ~100 MB of shared library pages
(PSS 421 MB against RSS 524 MB at idle).

| Build | Stage | Requests | p50 | p95 | p99 | 503 | Error % | Peak RSS MB | CPU % |
|---|---|---|---|---|---|---|---|---|---|
| **Before** (32953ce) | 25u | 154 | 4,375 | 20,610 | 30,027 | 0 | 3.25 | 1,498 | 93.5 |
| | 50u | 169 | 20,103 | 30,030 | 30,031 | 37 | 30.18 | 1,821 | 98.9 |
| | 100u | 534 | 1,173 | 26,318 | 30,031 | 378 | 73.60 | 1,983 | 98.9 |
| | recovery | 58 | 20,385 | 30,030 | 30,031 | 32 | 67.24 | 2,006 | 98.9 |
| **After** (this branch) | 25u | 248 | 686 | 5,909 | 13,330 | 0 | 0.81 | 1,037 | 81.0 |
| | 50u | 324 | 4,937 | 13,544 | 23,924 | 0 | 0.31 | 1,381 | 96.9 |
| | 100u | 362 | 7,727 | 21,190 | 27,718 | 155 | 43.65 | 1,556 | 98.9 |
| | recovery | 58 | 20,839 | 30,020 | 30,030 | 17 | 36.21 | 1,656 | 98.1 |

**Before → after.**
- **25 users (expected peak):**
  - p50: 4.4 s → 0.69 s;
  - p95: 20.6 s → 5.9 s;
  - errors: 3.25% → 0.81%;
  - throughput: 1.71 → 2.76 req/s at the same user count, because users stop
    waiting and click on.
- **50 users (2× peak):**
  - errors: 30.2% → 0.31%;
  - p50: 20.1 s → 4.9 s;
  - p95: 30 s → 13.5 s.
- **100 users:** errors 73.6% → 43.7%. The guard sheds load (503) instead of
  letting requests time out.
- **Memory:** peak down 460 MB at 25 users and 440 MB at 50.
- **Not achieved:**
  - 2× peak is not "reliably fast": p95 is 13.5 s at 50 users.
  - The 30 s recovery window after the 100-user stage does not drain the
    backlog: its single user still waits ~20 s.

The single CPU is at 97–99% from the 50-user stage on in every build. The
remaining cost is CPU per request (~290–310 ms of server CPU per request on average),
spread across many pages rather than concentrated in one. §7.3 sizes the
capacity change this calls for.

### 3.4 Memory and scale-out variants (current code)

| Variant | Stage | p50 | p95 | Error % | Peak RSS MB |
|---|---|---|---|---|---|
| A. Default allocator | 25u / 50u / 100u / rec. | 686 / 4,937 / 7,727 / 20,839 | 5,909 / 13,544 / 21,190 / 30,020 | 0.81 / 0.31 / 43.65 / 36.21 | 1,037 / 1,381 / 1,556 / 1,656 |
| B. `MALLOC_ARENA_MAX=2` | 25u / 50u / 100u / rec. | 819 / 5,088 / 7,389 / 20,097 | 5,968 / 15,598 / 22,335 / 26,790 | 0.82 / 0.32 / 42.03 / 11.86 | 1,075 / 1,101 / 1,101 / 1,129 |
| C. B + `--max-requests 300 --max-requests-jitter 60` | 25u / 50u / 100u / rec. | 1,068 / 4,526 / 1,818 / 20,884 | 5,438 / 16,191 / 19,188 / 27,986 | 0.84 / 0.95 / 63.0 / 30.0 | 1,031 / 1,139 / 1,140 / 1,059 |
| D. 2 CPUs, 4 workers, shared Redis, arena cap, guard 4/worker | 50u / 100u / 250u / rec. | 577 / 5,938 / 240 / 19,685 | 4,178 / 18,421 / 20,805 / 28,646 | 0.19 / 1.72 / 67.44 / 30.51 | 1,770 / 1,988 / 2,162 / 2,166 |

**Reading the variants.**
- **B (arena cap)** stops the memory climb at the same latency. It ships in
  the image.
- **C (worker recycling)** adds no memory gain over B. On one CPU, each
  restart costs throughput: 50-user errors rose from 0.32% to 0.95%, and
  100-user shedding from 42% to 63%. It is not recommended.
- **D (2 CPUs, 4 workers, Redis)** at 2× expected peak (50 users):
  - p50 4.9 s → 0.58 s;
  - p95 13.5 s → 4.2 s;
  - errors 0.19%;
  - CPU 157% of 200%.
- **D at 100 users** saturates both CPUs (p95 18.4 s) but sheds only 1.7%.
- **D at 250 users** refuses 67% as 503, so 500 was not run; it would
  measure only the refusal path.
- **Resources in D:**
  - Postgres connections peaked at 18: 4 workers × 4 slots, plus the
    scheduler. That is within the 25-connection direct limit.
  - Redis clients peaked at 74.
- **Recovery** after the 250-user stage still took longer than 30 s to drain
  in every shape.
- **Measurement caveat.** The first D run shared CPU 1 with test suites I was
  running and was discarded. These figures are from a clean rerun on an idle
  machine.

### 3.5 Single-request route sweep (every GET route, five roles)

Every argument-free GET route was requested once per role (CCEO, PL, CD,
IA, accountant): in-process, one request at a time, on a fresh copy of the
scaled data. 902 route/role pairs returned 200 in both runs.

| Across the 902 pairs | Before | After |
|---|---|---|
| p50 / p95 / p99 latency | 29 / 2,006 / 5,675 ms | 32 / 975 / 4,709 ms |
| Slowest pair | 10,850 ms (accountant `/ssa`) | 6,036 ms (accountant team planning oversight) |
| Sum of all latencies | 332 s | 212 s (−36%) |
| Queries, total / worst pair | 18,988 / 2,482 (CD `/core-schools`) | 14,795 / 3,432 (see closure note) |
| Database time, total | 112 s | 60 s (−47%) |

**Largest gains.**
- SSA workspace: 10.2–10.9 s → 1.8–3.8 s for CD, IA and accountant; PL
  5.8 s → 0.9 s; CCEO 3.3 s → 0.4 s.
- SSA export: ~10.5 s → ~1.8 s.
- Business transformation and loans pages: 4.7–5.1 s → 0.10–0.17 s.
- PL dashboard: 1.5 s → 0.06 s.
- CD Core Schools: 2,477 → 65 queries.

**Pairs that looked slower, re-measured.** 23 pairs were more than 1.5× and
100 ms slower. That sweep ran while test suites shared the database, and its
baseline ran on an earlier state of the template, so every flagged pair was
re-timed.

- **Re-timing method:** `main` (ffa2431) and this branch, each on a fresh
  template copy, one after the other on an idle machine, median of three.
  - 10 of the 13 pairs still slower were `/analytics` and its variants, with
    identical query counts.
  - Timed directly with the snapshot cache cleared between requests, a cold
    build is equal on both sides. The CD cockpit builds in 6.5 s here against
    8.0 s on `main`, and cache hits are 10–15% faster on the branch.
  - The sweep's medians fell between a hit and a miss, depending on where the
    30 s cache expiry landed in each pass.
- **Planner drawer and visit-effectiveness:** equal under the same controlled
  timing.
- **Closure queue:** which role pays for re-deriving stale checklists (R10)
  depends on who visits first. Under load it is as slow on `main` as here.
- **`/declining-schools`:** the one-off 24× count burst (R15) landed on it.
  Re-timed, it matches `main`.

**Conclusion.** No route is slower on this branch under equal conditions.

**Still slow single-request.** Pages above 2 s with no concurrency:
- Team and country planning oversight for country roles, 4.6–6.0 s: R2.
- Accountant blocked accounts, 5.7 s.
- The planning-oversight exports.
- Cold analytics cockpit builds, 2.7–6.5 s. These are cached for 30 s per
  user behind the stampede lock.

### 3.6 Soak

Production shape (1 CPU, 2 workers, no Redis) with the image's
`MALLOC_ARENA_MAX=2`. Four 5-minute windows at 24, 25, 26 and 27 users, so
drift shows up window by window, then 30 s of recovery.

| Window | Requests | p50 | p95 | p99 | Errors | Peak RSS MB | CPU % |
|---|---|---|---|---|---|---|---|
| 24 users | 776 | 513 | 3,929 | 9,118 | 0.00% | 1,058 | 73 |
| 25 users | 883 | 485 | 3,914 | 8,354 | 0.00% | 1,111 | 76 |
| 26 users | 895 | 506 | 4,355 | 10,162 | 0.00% | 1,168 | 80 |
| 27 users | 867 | 900 | 6,823 | 13,809 | 0.35% | 1,200 | 90 |
| recovery | 11 | 2,100 | 12,748 | — | 0.00% | 1,184 | 22 |

**What held for 20 minutes.**
- No worker restart.
- No 503 or 5xx at 24–26 users.
- No lock waiters; at most 3 sessions idle in a transaction; at most 14
  database connections.
- The queue drained after the load stopped.

**What it shows.**
- Latency at 24–26 users is stable window to window. It is not degrading
  over time.
- At 27 users the single CPU reaches 90% and p95 jumps to 6.8 s. This is the
  same cliff as §3.3, arriving just above the expected peak.

**Not proven.** Summed RSS rose from 1.06 to 1.20 GB, and the growth slowed
(+53, +57, then +32 MB per window). Worker caches filling (LocMem snapshots,
the URL-resolution LRU) would look like this. So would a slow leak, and a
20-minute run cannot tell them apart. A multi-hour soak on the resized staging
service, with the System Health memory alert watched, is still owed before
2× peak is declared supported.

**Measurement note.** My profiling of `/analytics` shared the database during
the first ~6 minutes. The 24-user window may be slightly pessimistic.

## 4. Database Performance Report (26.4)

**Where the time went.** On the scaled data, the SQL on the slowest pages was a
small share of request time once JIT was off. The dominant costs were:

- **Python-side:** building rows, model instances and templates;
- **how queries were shaped:** literal `IN` lists of thousands of ids, whole
  querysets evaluated just to test for emptiness, and correlated N+1s.

The main database finding was JIT.

| Finding | Evidence | Change |
|---|---|---|
| JIT compilation on complex ORM plans | Lending KPI: 4.7 s JIT compile against 76 ms execution (`EXPLAIN ANALYZE`) | `jit=off` in the connection options and as a role default for pooled sessions; readiness shows `db_jit` and reports `degraded` if a pooled session still has it on |
| Literal `IN` lists of 700–16,000 bind parameters | Query capture (`scripts/profile_request.py`) on the SSA, planning and staff-split paths | Subqueries (`values("id")`) or one `unnest(%s::varchar[])` array parameter |
| QuerySet truthiness | `qs or Model.objects.none()` fetched the whole scope (8 sites) | `scoping.or_empty` |
| `NOT IN (subquery)` with NULLs | Exclusion lists built from nullable `school_id` | `school_id__isnull=False` on the subquery |
| Writes on GET | Core Schools self-heal: ~550 single-row writes per view | Bounded bulk batch in one transaction |
| Non-deterministic ordering | SSA breakdowns and past-due tables tied on sort keys | `id` tie-breakers (output identical run to run) |

**Query counts (pinned by tests).**
- Country portfolio, cluster lens: `assertNumQueries(14)`, down from 15.
- Core Schools self-heal: at most 10 statements whatever the batch size.
- The route sweep (§3.5) records per-route query counts before and after.

**Checked and not changed.**
- **Team planning oversight (PL, scaled):**
  - The main activity query plans as a parallel hash join and executes in
    85 ms for 9,178 rows.
  - The page's ~1.1 s cost is Django instantiating 56k model objects: the
    activity plus six `select_related` relations per row.
  - Fixing it means building items from `values()` projections, a refactor of
    `oversight_service._activity_item` and its consumers. It is recorded as
    residual R2 and was not started here.
- **`target_ledger_sync` job:** 24 users, 145 queries, 425 ms per run, every
  30 minutes, on the scheduler process. Not a bottleneck; left as is.
- **Indexes:** no sequential scan on the hot paths was large enough to matter
  at this scale (`activity` 23k rows, `school` 16k). No index was added without
  a measured plan that needed it.

**Connections.**
- Production uses `CONN_MAX_AGE=0` against the direct port, and the guard caps
  each worker at 6 concurrent database requests.
- Peak connections in every load run, before and after, were 11–14 (limit
  25).
- `idle in transaction` peaked at 1–3 sessions per sample, the same before
  and after: requests between statements inside `ATOMIC` blocks, never
  accumulating.
- At most one lock waiter was seen, only in the first 25-user stage of each
  run (sign-in writes), and none later.
- Pool exhaustion is not the saturation mechanism; CPU is.

## 5. Frontend Performance Report (26.5)

Measured in Chromium (CDP Performance metrics, heap snapshots with the
`detachedness` field, ApexCharts render counting) against the demo dataset.

| Finding | Evidence | Change | Guard |
|---|---|---|---|
| Every HTMX swap redrew every chart | `htmx:afterSwap` dispatched `edify-theme-change`; 2 renders (~330 ms main thread) per swap on /ssa | Dispatch removed. Theme toggle still redraws. The PL programmes chart skips redraw when disconnected | `e2e/htmx-swap-cost.spec.js` (fails on old code with 2 renders) |
| Swapped-out chart panels retained | Heap retainer paths: window listeners of standard chart wrappers; `svg-typography` ResizeObserver holding detached SVGs; map component's 4 global listeners | Wrappers join `EdifyChartSystem._live` sweep; observer unobserves detached targets; map `destroy()` | HR Map/Operations cycling: ~7,500 → ~4,000 detached nodes per cycle |
| Prefetch competed with real users | Speculation rules prefetched analytics/IA views on 200 ms hover | `conservative` eagerness; server refuses `Sec-Purpose: prefetch` when no slot is free | 2 guard tests |
| Background tab kept posting | Reading tracker posted an empty heartbeat every 15 s | Beat only when there are seconds to report | — |
| Offline outbox replayed another officer's saved action | IndexedDB outlives sign-out; replay used the current session | Opaque per-account owner token (`salted_hmac`); only the owner's or legacy entries replay; others are kept, not dropped | `e2e/field-outbox-owner.spec.js` |

**Checked, not changed (recorded as residuals).**
- HR map-tab cycling still retains ~4,000 nodes, ~900 listeners and ~1 MB per
  cycle. The retainer path runs through Alpine's reactive proxy map, and a
  field-nulling experiment had no measured effect, so it was reverted rather
  than kept as a guess. (R4)
- The service worker never stores a page navigation, so it cannot serve one
  user's page to another. On a deploy it deliberately takes over at once
  (`skipWaiting`, `clients.claim`) and deletes the previous build's asset
  cache; `test_release_provenance` pins this. A tab left open across a deploy
  keeps the old build's page until it is reloaded, and nothing prompts the
  user to reload. That is a UX note, not a freeze cause. (R6)
- My Plan defaults to the whole FY by owner decision: 988 KB of HTML for a
  CCEO on scaled data. (R3)
- PL team planning oversight renders 1.9 MB of HTML. It is paginated per
  officer per table, but a PL with 12 officers gets 48 paginated tables on one
  page. (R2)

**Not claimed.** No Lighthouse or Core Web Vitals run was made against a
production-like CDN. The browser figures above are main-thread and
heap measurements on a local server.

## 6. Legacy Code Report (26.6)

**Method.** Each candidate was checked, and nothing was removed for being absent
from the navigation. The checks were:
- static imports and includes;
- dynamic template names and import strings;
- tests, e2e specs and scripts;
- the generated manifests in `docs/` (page, component, card, KPI and UI-surface
  inventories; permission matrix; traceability matrix);
- git history.

The manifests matter: several "unused" templates are still named there. Deleting
them means regenerating those manifests in the same change, and some tests read
template source directly.

### Removed in this release

| Item | Evidence | History |
|---|---|---|
| `apps/projects/presentation.py` (`training_project_options`) | No importer, no caller, no dynamic import, not named in any manifest or doc | Kept in git at 7489194 |

### Classified, not removed (recommendation per item)

| Item | Evidence | Classification | Recommendation |
|---|---|---|---|
| `/planning/intelligence` → `planning_intelligence_view` | Renders `partials/planning/right_panel.html`, which does not exist: any request with `?school_id=` raises `TemplateDoesNotExist` (500). No link, include or JS points at the route. Listed in the permission matrix and page inventory. `test_scope_and_period_integrity` inspects its source | Broken orphan | Remove the route, view and scope test together, regenerate `build_permission_matrix` and `build_page_inventory` |
| `staff_views` notification badge view | Renders `partials/notifications/notification_badge.html`, which does not exist. Unrouted | Dead | Remove with the view |
| `apps/planning/checks.py` | A `@register(deploy=True)` system check, but nothing imports the module, so the check has never run | Dead, not harmless: a check someone believed was active | Owner decision: wire it into `PlanningConfig.ready()` (it runs DB queries on `check --deploy`) or delete it |
| Unrouted views: `extended_views.ssa_master_view`, `core_schools_view`, `help_view`; `staff_views.today_view`; `hr_views.strategic_priorities_view`; `ClusterCreateView`; `SsaUploadView` | No URL pattern references them | Dead | Remove with their templates once manifests are regenerated |
| Templates with no include/render (`components/card.html`, `registered_card*.html`, `input.html`, `mobile_filter_sheet.html`, `kpi_strip.html` shim, `pages/partner/today.html`, `pages/fund_requests/detail.html`, `partials/analytics/cd/performance_vs_target.html`, `target_by_pl.html`, `partials/finance/accountant_insights.html`, `fund_allocation_kpis.html`, `partials/my_plan/activity_table.html`, `priority_queue.html`, `_priority_group.html`, `partials/oversight/cluster_performance_workspace.html`, `partials/projects/delta_pill.html`, `plan_activity_table.html`, `pages/ssa/index.html` (rendered only by an unrouted view), `pages/hr/strategic_priorities.html`) | No runtime reference; several are read by design-system or chart-contract tests (`test_mobile_foundation`, `test_bar_chart_system`) and named in the inventories and `docs/COMPONENTS.md` | Unused at runtime, still under test | Remove per family with the tests that pin them and a manifest regeneration; a separate change so a reviewer can see each removal |
| `static/css/components/record-views.css`, `static/js/record-views.js` | Not loaded by any template; the JS is referenced by a test only | Unused asset | Remove with its test |

**Not touched, by rule.**
- Models, migrations, historical tables and workflow states were not changed:
  none was proven unused, and history must be preserved.
- The compatibility redirects are live URLs that users may have bookmarked.
  They stay.

**Performance relevance.** None of the unused items is on a request path, so
removing them changes maintainability, not speed. Every measured slowdown in
this report came from live code.

## 7. Infrastructure Report (26.7)

### 7.1 Production shape today

| Service | Spec (`.do/app.yaml`) | Observation |
|---|---|---|
| Web | `apps-s-1vcpu-1gb-fixed`, 1 instance, `WEB_CONCURRENCY=2`, Uvicorn workers, guard 6/worker | CPU-bound: 83–99% of the one CPU from the 25-user stage on, in every run before and after the fixes |
| Scheduler | `apps-s-1vcpu-0.5gb`, 1 instance | Hardened in this release (§2, F15–F16) |
| Cache | None (`REDIS_URL` unset) | Each worker builds its own snapshots |
| Database | Managed PostgreSQL, direct connection, `CONN_MAX_AGE=0` | 11–14 connections at peak; not the bottleneck |

### 7.2 Cache and Redis

Every cache site in `apps/` and `config/` was audited. No cross-user leak was
found: each cache that holds one person's data carries `user.id` in its key,
and the analytics and impact caches also carry a scope fingerprint. There are
no `{% cache %}` tags and no `@cache_page` on authenticated views. Three
defects were found and fixed:

| Defect | Effect | Fix | Guard |
|---|---|---|---|
| Stampede waiters gave up after a flat 3 s and rebuilt the snapshot themselves | Any snapshot slower than 3 s to build (System Health cold ~6 s, the impact dashboard) was built once per waiter, all at once, on one CPU | Waiters wait while the rebuild lock is held, bounded by the lock's TTL; they build only if the owner finished without publishing | 3 tests (outlasts a 6 s rebuild; owner released without a value; wait stays bounded) |
| To-Do "forget" deleted the key without the build namespace | A completed or snoozed item stayed on the queue until the 15 s snapshot expired | `cache_utils.forget_snapshot` applies the namespace; `forget_queue` uses it | 2 tests |
| SLO-breach counter keyed on the concrete path | One process-lifetime dict entry per slow record, and three slow opens of three schools never counted as one slow route | Keyed on the route pattern | 1 test |

**Recorded, not changed.**
- Role dashboards (`cached_role_dashboard`) key on user and role but not
  scope. After a supervisor or school reassignment, the old portfolio can be
  served for up to `DASHBOARD_CACHE_SECONDS` (300 s). Adding the scope
  fingerprint to every hit costs a full scope resolution (~126 ms for a PL),
  which would erase the cache's benefit. The cheaper fix is a scope revision
  bumped on assignment changes. (R7)
- Every `Activity` save bumps one global analytics revision, invalidating
  every user's analytics cache at once. This is correct, but it produces
  rebuild waves under heavy data entry. (R8)
- Production has no Redis (`REDIS_URL` unset, by design at one instance), so
  each Uvicorn worker has its own cache. Two workers mean two cold caches and
  two rebuilds. System Health already reports the cache as "unshared".

### 7.3 Capacity

**What the measurements say.**
- On one vCPU, request CPU saturates the core from the 25-user stage on
  (81–99%). A request costs ~290–310 ms of server CPU on average, so one CPU
  tops out near 3–3.5 requests per second. 2× expected peak offers about
  5.5.
- Two workers need 1.0–1.4 GB (real, arena-capped ≈1.0–1.1 GB) against a
  1 GiB instance.
- Doubling the CPU and the workers (variant D) takes 2× peak from p95 13.5 s
  to 4.2 s, with 0.19% errors and CPU headroom left.

**Recommendation.** This is a budget decision for the owner; `.do/app.yaml`
records a cost ceiling for the estate.
1. **Web: 2 vCPU with 4 GB**, dedicated CPU for predictable latency (the local
   runs pinned real cores).
   - Run `WEB_CONCURRENCY=4` and `WEB_MAX_CONCURRENT_REQUESTS=4`: 16 database
     slots, plus the scheduler, stays within the 25-connection limit.
   - Alternatively, run two 1 vCPU / 2 GB instances.
2. **Add the managed Redis** the `.do/app.yaml` note already describes. It is
   required before a second instance, and it gives four workers one shared
   snapshot cache instead of four cold ones.
3. **Keep `MALLOC_ARENA_MAX=2`**, now in the image. Do not add aggressive
   `--max-requests`.
4. **Then rerun the 50/100-user stages** of `scripts/load_test.py` against the
   resized staging service before calling 2× peak supported.
5. **Beyond hardware**, the next biggest wins are:
   - R10: closure queue, read-only on GET;
   - R2: team and country planning oversight, ~5–6 s single-request for
     country roles on scaled data;
   - R15: the periodic count burst.

   These are the pages that keep p95 above ~4 s even with CPU to spare.

**Not recommended.** Buying CPU alone, without the code fixes. At 25 users
the "before" build spent ~550 ms of server CPU per request (1.71 req/s at
93.5% of one CPU, still timing out). This build spends ~290 ms (2.76 req/s at
81%). The same result without the fixes would take about twice the CPU, and
1.5–2.0 GB for two workers. The fixes in §2 are what make 2 vCPU enough for
2× peak.

### 7.4 Monitoring now in place

| Signal | Where | Threshold / use |
|---|---|---|
| `Server-Timing: app, db ("N queries"), queue, total` | Every response to a signed-in user | Read in browser devtools. Separates a slow page from a saturated worker |
| `slow_request` log line (JSON) | `edify.perf` logger | `SLOW_REQUEST_MS` (1,500) or `SLOW_REQUEST_QUERIES` (150). Fields: route **pattern**, method, status, role, htmx, total/app/db/queue ms, queries, bytes, release, correlation id. Never the path, user or record |
| Interaction telemetry | `InteractionEvent` gains `status_code`, `query_count`, `db_ms`, `queue_ms` | Feeds the report below |
| Route Performance (System Health) | Per-route p50/p95/p99, db p95, queue p95, mean queries, 5xx over 24 h | Checks: `route_performance_slow_routes` (p95 ≥ 3 s), `route_performance_queueing` (queue p95 ≥ 1 s = add capacity), `route_performance_server_errors` (≥ 1% 5xx) |
| Readiness `db_jit` | `/api/health/ready` | `degraded` if a pooled session still compiles with JIT |
| SLO incidents | admin_ops detection, now per route pattern | 3 slow (> 3 s) requests on one route open an incident |
| Scheduler history | `ScheduledJobExecution`, `scheduler_health_check` | Unchanged; now survives a dropped connection |

**What to watch after deploy.**
- **Queue p95 in Route Performance.** Above 1 s means the admission guard is
  holding people back: the instance is out of CPU.
- **Web instance memory alerts and restarts.**
- **The share of `slow_request` lines by route.**

The first two answer the capacity question in §7.3 with production data.

### 7.5 Rollback

- **Code.** Every change is an ordinary commit on this branch. Rolling back is
  a redeploy of the previous image. No data migration has to be reversed.
- **Migration** `telemetry.0003_interaction_event_performance`. It adds four
  integer columns to `InteractionEvent`, a diagnostics table. The columns
  carry a database default (`db_default=0`), so the previous build keeps
  inserting rows after a rollback. Without it, every event would have failed
  on NOT NULL and been dropped silently. A code rollback therefore needs no
  schema rollback. To remove the columns, run
  `manage.py migrate telemetry 0002`; it drops only those four columns.
- **JIT.** Set `DB_JIT=on` on the service to restore the previous behaviour for
  direct connections. For pooled sessions, run
  `ALTER ROLE <runtime role> RESET jit`.
- **Timing header or log volume.** Raise `SLOW_REQUEST_MS` or
  `SLOW_REQUEST_QUERIES` to quieten the log. The header is informational and
  goes to signed-in users only.
- **Scheduler grace.** `MISFIRE_GRACE_SECONDS` in `runscheduler`. Returning to
  1 s restores the old skip-on-late behaviour, which is not recommended.
- **Frontend.** The asset `?v=` strings changed, so browsers fetch the new
  files. Rolling back restores the old strings, and browsers fetch those.

### 7.6 Client address behind the edge (security, found during the audit)

**Defect.** Every consumer took the **leftmost** `X-Forwarded-For` entry, which
is whatever the client sent:
- the web login throttle (`throttle_by_ip`);
- the audit context (`RequestContextMiddleware.ip_address`);
- the sign-in record (`LoginEvent.ip`).

The DRF route throttle keyed on the whole raw header string. Sending a fresh
`X-Forwarded-For` on every request therefore bought a fresh per-address login
window each time, which bypassed AUD-010. It also wrote an address of the
caller's choosing into the audit trail.

**Platform behaviour.** DigitalOcean documents that App Platform adds a
`do-connecting-ip` header carrying the connecting client's address, and uses
`X-Forwarded-For` for the address of its own ingress server. So on App
Platform:
- the leftmost XFF entry is the client's claim;
- the rightmost is DigitalOcean's ingress server.

**Change.** A single helper, `apps.core.client_ip.client_ip(request)`, reads
from, in order:
1. `settings.CLIENT_IP_HEADER`. Production default: `HTTP_DO_CONNECTING_IP`;
   docker-compose sets it empty, because nothing in front of that port strips
   a client-sent value.
2. `X-Forwarded-For` counted `settings.TRUSTED_PROXY_HOPS` from the right.
   Default 0: ignored.
3. `REMOTE_ADDR`.

Values that are not IP addresses are skipped. The helper is used by:
- the web login throttle;
- the DRF route throttle (`get_ident`);
- the audit context;
- the sign-in record.

The two throttles key on `throttle_ident(request)`. That is the trusted
address, else the raw `REMOTE_ADDR`, which the server sets and is safe to
count against even when it does not parse.

**Where the count lives.** A shared cache (Redis) holds a fixed one-minute
window. Without one, each process holds a sliding window. The check that
chooses between them, `_cache_is_shared()`, read the type of
`django.core.cache.cache`. That object is a proxy, so the check reported
"shared" for every backend, and a deployment without Redis counted in a
per-process fixed window in local memory. It now reads the configured
backend.

**Tests.** `apps/core/tests/test_client_ip.py` covers:
- a rotating spoofed leftmost entry does not reset the window, with and
  without a trusted proxy;
- the proxy-appended entry, or the platform header, is the identity;
- with no header the key is the peer;
- the API throttle and the audit context use the same address;
- end to end, `/login` attempts with a fresh fake `X-Forwarded-For` each
  reach 429. The test sends seven against a limit of three, so a minute
  boundary between two of them cannot hide the limit.

**To confirm on deploy.** Sign in once and compare the new `LoginEvent.ip`
with the address you are connecting from. If App Platform does not send
`do-connecting-ip` for some route, the helper falls back to `REMOTE_ADDR`: the
ingress address, shared by everyone. That is safe against spoofing but makes
the limit coarse, so check it once.

## 8. Regression and Workflow Validation Report (26.8)

### 8.1 Tests added or changed by this release

| Area | Test | What it pins |
|---|---|---|
| Request timing | `apps/telemetry/test_route_performance.py` (10) | Server-Timing for signed-in users only; slow-request log names the route pattern, never the path, user or record; guard wait reaches the timer; telemetry persists status, queries, db and queue time; percentiles and health checks |
| Database session | `apps/core/tests/test_database_timeouts.py` | JIT is off in the live session |
| Readiness | `apps/system_health/test_health_probes.py` | Pooled path reads `jit`; JIT on reports `degraded`, never 503 |
| Core Schools heal | `apps/core_schools/test_self_heal_performance.py` (6) | Bounded bulk heal, statement ceiling, conflict fallback, SSA gate in the query, newest-first batch order |
| Query budget | `apps/planning/test_country_portfolio.py` | Cluster lens: 14 queries |
| Admission guard | `apps/core/tests/test_concurrency_guard.py` (+2) | A speculative prefetch never waits for a slot |
| Scheduler | `apps/realtime/tests.py` (+3) | A dropped connection does not fail the next job (fails on old code); 300 s misfire grace, coalesce, one instance; debrief jobs honour the gate |
| Cache | `apps/core/tests/test_cache_utils.py` (+5) | Waiters outlast a slow rebuild; build when the owner published nothing; bounded wait; namespaced forget; To-Do forget reaches its snapshot |
| Incident detection | `apps/admin_ops/tests.py` (+1) | Slow requests tallied per route pattern |
| Client address | `apps/core/tests/test_client_ip.py` (14); `apps/accounts/test_presence.py` (2 updated) | Platform header and right-counted hops are trusted, the client-written leftmost entry never is; rotating a fake `X-Forwarded-For` on `/login` still reaches 429; API throttle and audit context use the same address |
| Throttle backing | `apps/core/test_throttle_shared_backing.py` (+4) | Local-memory and dummy caches count in the in-process sliding window, Redis in the shared one (three fail on the old check) |
| Prefetch contract | `test_client_responsiveness`, `test_design_system_contract` (updated) | No `eager`, no `moderate` (hover), no prerender; pointer-down only |
| Browser | `e2e/htmx-swap-cost.spec.js` | An unrelated swap redraws no chart (fails on old code with 2); a theme switch still does |
| Browser | `e2e/field-outbox-owner.spec.js` | Offline outbox replays only the saving account's (and legacy) entries |

### 8.2 Output equivalence of the optimised paths

Each optimised service was compared, original commit against this branch, on
the same scaled database. Outputs were canonicalised before comparing.
- **SSA payloads and past-due rows:** at first they differed only in the
  order of tied rows. Both now sort with an `id` tie-breaker and compare
  equal.
- **`safe_mean`:** agreed with the pandas path on 60,004 random inputs, with
  0 mismatches.
- **Target ledger:** identical after a full rebuild (hash of every row).

The rendered-HTML comparison across every changed page is reported in §8.4.

### 8.3 Business invariants

No workflow state, model, migration of business data, permission rule or
financial path was changed. The invariants named in the brief are held by the
existing suites, which run unchanged:
- IA verification;
- separation of financial duties;
- record-level scope;
- one activity / one cost / one delivery channel;
- partner attribution;
- target reconciliation;
- audit history;
- canonical service transitions;
- planned / actual / verified separation.

The only behaviour changes a user can see:
- charts no longer redraw on unrelated swaps;
- the offline outbox holds another account's saved actions instead of sending
  them;
- the To-Do queue drops a decided item at once;
- SLO incidents group by route;
- analytics view links prefetch on pointer-down, not on hover;
- the login rate limit, the audit trail and the sign-in record use the
  address App Platform reports, not the client-supplied `X-Forwarded-For`.

### 8.4 Rendered-HTML equivalence (main vs this branch)

**Method.**
- 23 pages across CD, PL, CCEO, RVP, regional lead, IA, accountant and HR:
  - SSA, Planning, Core Schools, My Plan and dashboards;
  - team targets, team and country planning oversight;
  - schools, clusters, my targets, HR today, IA dashboard, disbursements,
    loans.
- Each page was rendered in-process, once on `main` (ffa2431) and once on
  this branch, each against its own fresh copy of the scaled database.
- Volatile tokens were normalised: CSRF, nonces, clock times, asset `?v=`
  strings, the outbox owner token and prefetch eagerness.

**Result.**
- **All 23 pages return 200 on both.**
- **14 pages are identical** apart from the shared layout lines this release
  changed on purpose: the chart wrapper is registered with the sweep, and
  `<body>` carries the outbox owner token.
- **Dashboards (CD, RVP, IA, PL, CCEO)** also differ in the regional map
  script: the new `destroy()` handlers.
- **The PL and CCEO dashboards and My Plan** differ only in the order of tied
  rows.
  - On My Plan the content is identical line for line, in a different order.
  - On the dashboards' paginated tables, the order also decides which tied
    rows land on page 1.
  - Main's own rendering of these pages changes the same way between two
    identical database copies (§9, R14), so this is main's existing
    non-determinism.
  - The branch now fixes the order of the PL past-due tables.
- **Core Schools (CD) and PL team targets** differ in *which* 50 schools the
  first page load heals.
  - This pass found a real change, now fixed: the bulk heal chose its batch by
    primary key instead of School's newest-first order.
  - It now uses the same order with `pk` as tie-breaker, pinned by
    `test_a_batch_reaches_the_newest_schools_first`.
  - The remaining difference is within one `created_at` tie of 2,334 schools,
    where main's pick is arbitrary.

## 9. Remaining Risks (measured, not fixed here)

| # | Risk | Evidence | Recommendation | Severity |
|---|---|---|---|---|
| R1 | **Capacity.** One vCPU saturates from the 25-user stage; at 2× expected peak (50 users) p95 is 13.5 s | §3.3 | §7.3 capacity change, then rerun the 50/100-user stages on it | **High** |
| R1b | **Memory.** Two workers exceed the 1 GiB instance from 25 users (1.04 GB) and reach 1.38 GB at 50. OOM restarts look like freezes and drop in-flight work | §7.3 | Resize before, or together with, R1 | **High** |
| R2 | Team planning oversight (PL, CD) builds 9,178 items as model instances: ~1.1 s of Python and 1.9 MB of HTML (12 officers × 4 tables) | Profile §4 | Build items from `values()` projections; lazy-load each officer's section | Medium |
| R3 | My Plan defaults to the whole FY: 988 KB of HTML for a CCEO | Owner decision | Revisit the default window with the owner | Medium |
| R4 | HR map/operations tab cycling retains ~4,000 nodes, ~900 listeners, ~1 MB per cycle through Alpine's reactive proxy map | Heap snapshots | Investigate the Alpine component lifecycle on those tabs | Low |
| R5 | Per-CCEO scope is bound as a literal id list (~780 parameters per scoped query) | Query capture | Scope as a subquery or array parameter throughout `apps.core.scoping` (architectural) | Low–Medium |
| R6 | A tab left open across a deploy keeps the old build's page until it is reloaded, with no update prompt | `pwa_views.py`, by design | Optional "new version" prompt | Low |
| R7 | Role dashboards can serve the previous portfolio for ≤300 s after a reassignment | Cache audit | Scope revision bumped on assignment changes | Low–Medium |
| R8 | Every Activity save invalidates every user's analytics cache | Cache audit | Scope the revision to affected portfolios | Low |
| R9 | Message attachments upload to Spaces inside the message transaction. A slow multi-file upload can hit the 60 s idle-in-transaction limit | `message_views.py:236,447` | Upload first, then create message and attachments in one short transaction; clean up orphans | Low–Medium |
| R10 | **Closure readiness queue writes on GET.** Every stale checklist (15 min) is re-derived in the request: ~1,000 statements, 297 inserts, 4.2 s for one IA view. 25 s median under load. Concurrent viewers duplicate the work | Profile, load test | Refresh checklists in a scheduled job; GET reads only; rewrite blockers only when changed | **Medium–High** for IA/accountants |
| R11 | Exports, LibreOffice DOCX→PDF and imports run synchronously in web requests. The audit seal runs under a global advisory lock in the request thread; ClamAV scanning runs inside a transaction in lending imports | Code audit | Move to the scheduler / a job queue as each surface is touched | Medium |
| R12 | The per-address login throttle trusts the client-supplied leftmost `X-Forwarded-For` | Cache/throttle audit | Derive the client address from the trusted proxy hop | Medium (security) |
| R13 | `ScheduledJobExecution` history is never pruned; job locks are not renewed for runs longer than 4× their expected runtime | Scheduler audit | Prune history in `mfa_challenge_purge`-style maintenance; heartbeat the lock | Low |
| R14 | Some tables have no fixed order for tied rows: My Plan, and the CCEO and PL dashboard tables. The same page rendered on two identical database copies on **main** differs by 32,750 lines on My Plan and 170–378 on the dashboards. On a paginated table, a row can move between pages from one load to the next, so a reader can miss or see a row twice | HTML equivalence pass (§8.4) | Add an `id` tie-breaker to each list's `order_by`, as this release did for the PL past-due tables and the SSA breakdowns | Low–Medium |
| R15 | A burst of ~24 identical `COUNT(DISTINCT activity.*)` statements (1.5–2 s of database time) lands on an arbitrary request from time to time. In the sweep it hit IA `/declining-schools` on main and CD `/declining-schools` on this branch; a single request of the same page issues 12 statements | Route sweep records (`max_repeat` 24) | Find the periodic in-process recompute that issues it (likely a short-TTL badge or count cache), cache it longer, and count ids rather than distinct whole rows | Medium |

## 10. Acceptance Checklist and Release Decision

| Requirement | Status | Evidence |
|---|---|---|
| Freezes reproduced before fixing | Met | §2, §3.3 "before" rows |
| Request-level instrumentation in production | Met | §7.4 |
| Bottlenecks identified with evidence | Met | §2, §4 |
| Critical bottlenecks fixed and re-measured | Met for 18 of the 20 in §2; F17 (capacity) and F19 (closure queue) are open with designs | §2, §3.3 |
| Output unchanged by optimisations | Met, one real difference found and fixed | §8.2, §8.4 |
| Business invariants preserved | Met: no workflow, permission, financial or history change | §8.3 |
| Role-weighted concurrent load test, 25/50/100 | Met | §3.3 |
| 250 / 500 users | 250 run on the scaled-out shape; 500 not run | §3.4 |
| Reliably fast at 2× expected peak on current infrastructure | **Not met**: p95 13.5 s at 50 users | §3.3 |
| Memory within the instance | **Not met**: ≈1.0 GB real with the arena cap (at the 1 GiB limit, no headroom), up to ≈1.5 GB without | §3.4, §7.3 |
| Soak test | **Partly met**: 20 min at 24–27 users was stable with no restarts; memory drift over multiple hours not yet shown | §3.6 |
| Scheduler and integrations audited | Met; two resilience defects fixed, the rest recorded | §2 F15–F16, §9 |
| Cache isolation and stampede protection | Met; no cross-user key; three defects fixed | §7.2 |
| Legacy code removed only with proof | Met: one module removed, the rest classified | §6 |
| Regression tests for every fix | Met | §8.1 |
| Monitoring and rollback documented | Met | §7.4, §7.5 |
| CI green | **Not yet**: 9 failures and the format check are red on `main` too | PR comment |

### Release decision

**GO to deploy this release**, as a strict improvement, on two conditions:
1. The `main`-branch CI failures are resolved and this branch's CI is green.
2. `LoginEvent.ip` is checked once after deploy (§7.6).

The image now sets `MALLOC_ARENA_MAX=2` itself.

This release:
- removes the measured freeze causes;
- cuts errors at 2× expected peak from 30% to 0.3%;
- adds the monitoring that tells a slow page from a saturated instance;
- changes no business rule.

**NO-GO on declaring the platform ready for 2× expected peak** on the current
1 vCPU / 1 GiB web instance. At 50 concurrent users p95 is still 13.5 s, and
two workers need more memory than the instance has. Readiness needs the
capacity change in §7.3 plus a rerun of the 50/100-user stages on it, which
this programme sized but cannot apply to production itself.
