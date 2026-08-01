# Performance, scalability, reliability and design audit — 31 July 2026

Scope: stability, performance, scalability, reliability, consistency, speed,
accessibility and responsiveness, audited and repaired rather than only
reported.

Everything below was measured against the existing 15,000-school scale fixture
(`apps/system_health/test_load_scale.py`), which runs `ANALYZE` after its bulk
inserts — so the timings reflect real plans rather than stale planner
statistics.

---

## 1. How the defects were found

The measurement harness mattered more than any individual fix. A profiler
subclassed `ScaleGateTest`, neutralised the inherited assertions, and walked
every main route reporting wall time, SQL time, query count, and — decisively —
**repeated query shapes**. Counting identical SQL prefixes is what turned a page
that merely "felt slow" into a specific loop with a line number. Every
performance defect in this document was located that way.

Two findings would not have surfaced any other way:

- `/clusters` was returning **HTTP 500** at 15,000 schools. The scale gate
  passed it because the gate asserts *query-count invariance as the estate
  grows*, and a page that crashes early issues a very stable number of queries.
- The scale fixture was writing the display label `"Government Requirements"`
  into `SsaScore.intervention` instead of the canonical value
  `government_requirement`. Every intervention rollup the gate exercised was
  therefore matching nothing, and had been measuring an empty code path.

---

## 2. Measured results

Wall time, query count and SQL time per route, before and after.

| Route | Queries | Wall | SQL |
|---|---|---|---|
| `/clusters` | 141 → **33** | HTTP 500 → **180ms** | — → **101ms** |
| `/analytics` | 193 → **78** | 616ms → **356ms** | 453ms → **254ms** |
| `/help` | 325 → **55** | 448ms → **167ms** | 265ms → **94ms** |

`/clusters` had no meaningful "before" wall time because it never completed. Its
first honest measurement after the crash fix was 605ms, of which 526ms was
Python materialising SSA records; pushing those rollups into SQL brought the
page to 180ms.

The full suite is green with every change in this document: **3,470 passed, 2
skipped, 0 failed**.

---

## 3. Performance and scalability defects fixed

### 3.1 `/clusters` returned 500 at scale — and the fixture hid it

`apps/clusters/services.py` indexed a dict of enum values directly with a stored
column value:

```python
intervention_scores[score.intervention].append(score.score)
```

`SsaScore.intervention` is a `CharField` with `choices`, and Django does not
enforce choice membership at the database level. One legacy or mis-mapped row
raised `KeyError` and took down the entire cluster list. The surrounding code
builds its output by iterating the enum, so a value outside the enum was never
displayed even when it was collected — the lookup was pure fragility. It now
skips unknown values.

The same bug existed in `cluster_weakest_interventions`, on the same page.

The fixture defect is fixed separately, so the scale gate now actually exercises
intervention rollups.

### 3.2 `/clusters` was unbounded in the size of the estate

The card loop queried per cluster *and per school within each cluster*:

```python
for c in filtered_qs...:
    schools = School.objects.filter(cluster_id=c.id, ...)
    for s in schools:
        latest = _latest_confirmed_ssa(s)   # one query per school
```

With 136 clusters and 15,000 clustered schools that is O(clusters × schools).
The scale gate never caught it because the gate grows *schools*, and this loop's
cost is dominated by a dimension the gate holds constant.

Rewritten to a fixed number of queries for the whole page: one pass for school
counts and staff, two grouped activity aggregates replacing three queries per
cluster, and the SSA rollups computed by the database rather than in Python.
That last part matters on its own — the intermediate fix loaded every clustered
school's latest SSA record plus its eight scores, roughly 120,000 model
instances per request, which was the single largest cost on the page.

`covered_sub_counties` is now prefetched instead of queried per card.

### 3.3 `/help` re-seeded the entire Knowledge Center on every page load

`ensure_canonical_content()` ran on every Help request: 129 article lookups and
124 glossary `get_or_create` calls, 325 queries to confirm rows that were
already there. The content is installed by the `post_migrate` reference-data
hook, so the request path was only ever re-confirming it.

Rather than strip the call sites — which would lose the self-healing property —
`ensure_canonical_content()` now short-circuits on a three-query completeness
check and still falls through to the full seeding pass whenever anything really
is missing.

### 3.4 `/analytics` — five per-item loops and a duplicated KPI query

Five loops each issued two to five queries per item: months (24 queries),
interventions (8), districts (16), regions (4 per region), clusters (5 per
cluster). All are now single grouped aggregates.

The KPI block issued twelve separate `COUNT`/`SUM` queries against two
querysets; they are now two `aggregate()` calls using conditional aggregation.
The joins are all many-to-one (`activity → school`), so there is no row fan-out
to distort the sums. Card 8 ("Total Activities Completed") was running a query
byte-identical to Card 1's numerator and now reuses it.

The remaining `/analytics` cost is genuine full-estate aggregation, not a
defect.

### 3.5 Filter bar ran six full-table scans per render

`apps/filters/services.py` built each dropdown with
`set(base.values_list(col, flat=True))` — pulling every in-scope school row into
Python to produce at most a few dozen options, six times, on every filter-bar
render. Now deduplicated by the database.

Note for anyone touching this: `.order_by()` must clear School's default
`-created_at` ordering first. Leaving it in makes Postgres reject the `DISTINCT`
(the ordering column is not in the select list) and would defeat the
deduplication anyway, since every row's timestamp differs.

---

## 4. Reliability defects fixed

### 4.1 MFA held a database transaction across the provider round-trip

`apps/accounts/mfa_service.py::start_challenge` was decorated
`@transaction.atomic` and called `_deliver()` inside it, holding a database
connection for the whole SMS (10s) or email (15s) round-trip **on the sign-in
path**. With `MFA_REQUIRED_FOR_ALL` enabled and a slow provider, every
concurrent login pins a connection until the pool is exhausted.

The atomic block now covers only the writes; delivery happens after it. The
existing blocking-I/O guard flagged this in production but only logged and
proceeded, and the tests patch the send at the module boundary above the guard,
so nothing failed loudly.

### 4.2 No database connect timeout

`statement_timeout`, `lock_timeout` and `idle_in_transaction_session_timeout`
were all set, but these only bound queries on a connection that already exists.
Without `connect_timeout`, libpq waits indefinitely for the startup handshake —
and `CONN_HEALTH_CHECKS` means a reconnect can be attempted at the start of any
request. Set to 5s, overridable via `DB_CONNECT_TIMEOUT_S`.

### 4.3 Redis had no socket timeout, and a boot-time blip downgraded silently

The cache was configured with only a `LOCATION`, so every `cache.get`/`set` ran
with redis-py's defaults — no timeout at all. The 1s bound in the settings
applies only to the import-time probe, so a Redis that degrades *after* boot
blocks the worker on a cache read indefinitely. Socket connect and read timeouts
are now set.

Separately, if Redis was unreachable for even a moment at boot, the settings
fell through to `LocMemCache` with no signal. That is not an equivalent backend:
it is per-process, so each worker gets a private cache and anything written for
another worker to read is lost. It now logs a warning saying exactly that
(suppressed under test, where the fallback is expected).

### 4.4 Login throttle leaked memory

`apps/core/throttling.py` pruned timestamps *inside* each bucket but never
removed the bucket, and the key is `route:client_ip`. A long-lived worker
accumulated one permanent entry per distinct client address; an IP-rotating
credential-probe run against the login route grew it without bound. Buckets that
have gone quiet are now swept, at most once a minute, against the widest window
any caller has requested.

### 4.5 The monthly budget job could unlock an approved budget

`apps/realtime/jobs.py` passed `status` and `generated_by` in `update_or_create`'s
`defaults`, so a second run for the same month — a scheduler restart, or a manual
re-run after the envelope had gone to the RVP — reset an approved or disbursed
budget to `draft_generated` while its submission snapshots stayed put. The totals
repair would then treat it as live and overwrite the approved figures. Both
fields moved to `create_defaults`.

### 4.6 Target ledger silently lost credit across the fiscal-year boundary

`TargetAchievementLedger`'s unique constraint is deliberately FY-agnostic — one
source credits once, ever — but `my_targets.py` looked up existing rows filtered
by `fy`. When an activity's date was corrected across the boundary (September to
October), the new FY found no row, tried to insert a second one, hit the
FY-blind constraint, and `bulk_create(ignore_conflicts=True)` **swallowed the
rejection**. The new year gained no credit, the old year was never reversed, and
nothing was logged.

The lookup now spans the user's whole ledger and the row's `fy` follows the
activity. The stale-reversal sweep is explicitly scoped to the FY being rebuilt,
since it only knows which sources belong to that year.

---

## 5. Accessibility and responsiveness

Audited against the existing `ui_quality` and `page_inventory` tooling, focused
on the surfaces built since the July a11y sweep (Work Plan, Calendar, Knowledge
Center, Activity Catalogue).

Fixed:

- **Calendar month grid was unreadable to screen readers.** `role="grid"`
  contained `columnheader`/`gridcell` children with no `role="row"` between
  them; browsers drop orphaned cells from the accessibility tree entirely. Rows
  added, with `display: contents` so the seven-column layout is unchanged.
- **Nested `<main>`** on every Knowledge Center page — invalid HTML and two
  `main` landmarks.
- **Two `<h1>` per page** on four Help surfaces; heading levels realigned.
- **Work Plan "More filters" popover computed off-screen.** Absolutely
  positioned against its own ~130px `<summary>`; once the toolbar wrapped (at
  360/390/430px, and again near 1024px with the sidebar) its left edge landed
  around −134px, making four filters unreachable with no way to scroll to them.
  Re-anchored to the toolbar.
- **`pill-warning` matched no CSS rule anywhere** (the token is `pill-warn`), in
  two places. On the catalogue page colour was the only signal distinguishing
  "N open" from "none open", so the chip silently lost its meaning.
- **Duplicate `class` attributes** in two templates — parsers keep only the
  first, so the second set of classes never applied.
- Unlabelled inputs (Work Plan return reason, catalogue resolve form); an
  `aria-label` on a bare `<span>`, which assistive tech ignores; missing viewport
  meta on the standalone manual export; two non-collapsing two-column grids in
  the activity drawer at 360px.

**Correction to a standing assumption:** `xl:` *is* compiled — 34 rules in
`main.css`, and `ui_quality`'s `uncompiled_variants` check reports zero. The
real gap is plain arbitrary utilities that were never built (`min-w-[170px]`,
`min-w-[180px]`, `min-w-[230px]`, `scroll-mt-4`), which silently do nothing.
`ui_quality`'s regex only inspects variant prefixes, so it structurally cannot
catch them.

---

## 6. Open items, ranked

Not fixed in this pass. Listed so they are decisions rather than oversights.

**Closed after this document was first written:**
1. ~~`npm run build:css` to compile the four missing utilities above, and extend
   `ui_quality` to catch uncompiled non-variant utilities.~~ Done — see
   §8 below.

**Unbounded loads still on request paths** (the remaining scaling work):
2. `apps/analytics/ssa_performance_service.py` materialises 8 score rows per
   record — 120,000 rows at full estate — and `build_dashboard` does it twice
   for the comparison period.
3. `apps/frontend/views/extended_views.py` (map page) holds four copies of a
   15,000-school payload and a ~2MB `json.dumps` in template context.
4. `apps/analytics/cd_analytics_service.py` pins a 15,000-element id list per
   request and uses `tuple(sorted(...))` of it as a cache key.

**Correctness and operations:**
5. `rebuild_audit_chain` loads the entire `AuditLog` into memory under row locks,
   and its unbounded `update(seq=None)` nulls rows written after the snapshot —
   breaking the chain it exists to repair. `select_for_update` does not block
   INSERTs.
6. 83 `except Exception: pass` sites that do not log. Most are deliberate
   best-effort and commented as such; the silence is the problem. Two clusters
   matter: audit-chain writes for money events (which serialise on one global
   advisory lock with a 10s `lock_timeout`, so under contention they *will* time
   out and the money event vanishes from the tamper-evident chain), and
   notification delivery in money workflows.
7. The login throttle is per-process, so with N workers the 10/min limit is
   effectively 10×N. Fixing it means backing it with the shared cache, which
   needs a decision on fail-open vs fail-closed when Redis is down.
8. `send_pd_reminders` bypasses the scheduler lock and can duplicate
   notifications; `_log_sent` uses `get_or_create`, which de-dupes the log and
   therefore *hides* the double-send.
9. `admin_maintenance_generation` writes the work item and the template in two
   separate transactions with no uniqueness on `(template, due_date)`.
10. The readiness probe catches only `OperationalError`; psycopg3 raises
    `InterfaceError` on a dead connection, so a mid-outage probe returns an
    unhandled 500 instead of a clean 503.

**Design decisions, not defects:**
11. The Calendar filter strip's segmented-pill design in
    `calendar-workspace.css` is dead CSS — `platform.css` applies the tab
    contract with `!important` and wins. The strip renders as the platform
    underlined rail.
12. Sub-24px desktop targets (WCAG 2.2 AA 2.5.8) on `<summary>` toggles and
    inline submit buttons. Touch is already covered by a 44px minimum under
    coarse pointers; these fail only for a mouse, in the "inline, constrained by
    line-height" grey area of the criterion.

---

## 7. What was not verified

Stated plainly rather than implied as passing:

- **No browser verification.** All accessibility and responsive findings come
  from reading templates, compiled CSS and token definitions, plus computed
  contrast and container-width arithmetic. The `display: contents` grid
  behaviour, the popover re-anchoring and the drawer date-field widths are
  reasoned, not observed. They warrant a visual pass at 360px and 1280px.
- **No load or soak test** was run in this pass; the numbers here are
  single-request profiles, not concurrency or sustained-throughput measurements.
- The remaining unbounded loads in section 6 were identified statically and
  have not been profiled under load.

---

## 8. CSS bundle rebuild and the lint that should have caught it

### 8.1 The rebuild

`npm run build:css` was run against the working tree rather than a pristine
checkout, because both templates carrying the missing classes
(`pages/work_plan/index.html`, `pages/help/release_notes.html`) are themselves
uncommitted — a build from `HEAD` would not have contained the very utilities
this was meant to add.

`static/css/main.css` was clean against `HEAD` beforehand, so the diff is exact
and was verified selector by selector: **6 added, 19 removed**, bundle 314,253 →
312,006 bytes. Every removal was checked against `templates/`, `apps/`,
`static/js/` and the hand-written stylesheets, and all 19 are genuinely
unreferenced — mostly the raw-radius values (`rounded-[10px]` … `rounded-[16px]`)
that the design tokens replaced, and the `w-[280px]` popover width dropped when
the Work Plan filter panel was re-anchored.

`static/js/` deserves the explicit check: it is **not** covered by the `@source`
globs, so a class emitted only from JavaScript would be silently dropped by any
rebuild. None were.

Cache-buster on `main.css` bumped to `?v=20260731minw1`.

### 8.2 The new lint

`uncompiled_variants` inspects only `xl:`/`2xl:`-prefixed classes, so a plain
utility that was never compiled passed straight through it. That is precisely
how the four landed.

`uncompiled_utilities` closes the gap: it pulls every utility out of the
`class` attributes in `templates/`, and asserts each resolves to a real rule in
`main.css` or one of the hand-written `static/css/*.css` files. Two shapes are
extracted — arbitrary values (`min-w-[170px]`, `lg:grid-cols-[210px_minmax(0,1fr)]`)
and numeric scale steps on a fixed list of spacing/sizing prefixes. The prefix
list is deliberately restricted: a bare `foo-2` is far more likely to be a
hand-written class than a Tailwind one, and a lint that cries wolf gets switched
off.

Class attributes containing template syntax are skipped, since the fragments
around a `{% if %}` are not reliably whole class names. Lookups go through a
prebuilt set of unescaped class names rather than a substring scan of the
300KB bundle per class.

It considers 23,742 utility tokens across the template tree and reports zero.
Verified against a probe template that it flags all five failure modes —
uncompiled arbitrary value, invalid scale step, a utility dropped from the
bundle, and a `lg:`-prefixed arbitrary value that `_XL` structurally cannot see
— while leaving real classes (`mt-4`, `rounded-surface`, `edify-badge`) alone.

### 8.3 A fifth uncompiled utility, found by the new lint

`templates/partials/notifications/notification_drawer_list.html:44` used
`py-0.2`. There is no such step on the spacing scale — `0.5` is the smallest
fraction — so Tailwind generated nothing and the "Action" badge had no vertical
padding at all. Corrected to `py-0.5`.

### 8.4 Observation, not changed

`static/css/drawers.css:425-427` writes two Tailwind-shaped selectors without
escaping them:

```css
.drawer-body help-text,
.drawer-body .text-[10px],
.drawer-body .text-[11px] { color: var(--edify-text-subtle) !important; }
```

`[10px]` is not a valid attribute selector (attribute names cannot begin with a
digit), and one invalid selector invalidates the **entire** selector list — so
this rule has never applied, including its `help-text` arm. It is the only
instance in the hand-written stylesheets; every other unescaped `[...]` in
`static/css/` is a legitimate `[data-tone=…]`-style attribute selector.

Left alone deliberately. The two classes it targets no longer appear in any
template, so deleting the rule is a no-op and *fixing* the escaping would start
applying a colour override that has never been in effect — a rendering change
that cannot be verified here.
