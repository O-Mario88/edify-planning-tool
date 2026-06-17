# Edify — System-Wide Filter Accuracy Audit (2026-06-17)

> "A filter is a promise." When a user selects a region, the page must show only
> that region — every card, chart, table, list, export, and recommendation —
> computed at the backend query, never a cosmetic chip.

Method: 3 parallel deep-audit agents (role-scope leak · filter threading · FE
framework) → root-cause analysis → backend + FE fix → **live reconciliation vs
psql** → unit tests → browser verification. Repos: `edify-web` (Next 16) +
`edify-api` (NestJS/Prisma/Postgres `edify_pm`, clean 700-school DB).

---

## A. Executive Verdict

### ✅ Geography filtering is now backend-enforced and consistent across the page — verified live.

The audit found the **security core was already sound** (a filter can only
narrow, never widen past a user's role scope — **0 P0, 0 P1**), but the
**functional promise was broken**: selecting a district narrowed some parts of a
page and not others, because of a name↔cuid mismatch between the filter bar and
the backend. That is **fixed and verified live** — a selected geography now
narrows the KPI strip, the program snapshot, the SSA grids, the contribution
lens, and the directory rows + aggregate together, and the dropdowns now offer
the real backend districts.

| Dimension | Verdict |
|---|---|
| Role scope can't be widened by a filter | ✅ 0 P0 / 0 P1 (SQL-reconstructed + unit-locked) |
| Selected geography reaches the backend query | ✅ threaded through 10 analytics endpoints + `/schools` + contribution |
| Every part of the page obeys the filter | ✅ strip + snapshot + grids + contribution + rows now consistent |
| Filter dropdowns reflect real (live) data | ✅ options sourced from `/analytics/districts` (was mock portfolio) |
| URL state / shareable links | ✅ active label resolves from the URL (was stuck on "All Districts") |
| Tests | ✅ api 136 (+9) · web 594 (+4) · both build clean |

---

## B. Security — Role Scope Cannot Be Widened (0 P0 / 0 P1)

The #1 trust item (this protects what leadership is allowed to see). Verified by
the scope-leak agent via SQL reconstruction + live probes + DTO checks:

- Every filter-accepting endpoint applies the **role scope first**
  (`aggregateSchoolWhere` / `schoolWhere`), then ANDs the geography filter on a
  **different Prisma key** (`district`/`region`/`clusterId`) — **never `id`**.
  So a scoped user passing an out-of-scope district intersects to **0 rows, not a
  leak** (Gulu-scoped user + Apac filter → 0).
- Lens gating (`canGroupByCceo`, team lens) returns **403**, not silent data.
- FY param is injection-safe; the FE→BE bridge mints a role-correct JWT and can't
  escalate.
- Locked by `geo-filter.spec.ts`: `geoWhere()` never emits `id`, and composes
  with an `id IN (...)` scope by AND (narrow-only).

---

## C. Root Cause — the name↔cuid mismatch

The FE filter bar emits a district **name** (`"Gulu"`) and a region **key**
(`"northern"`); the backend `District`/`Region` rows use cuids (the `code`
column that would hold the canonical `UG-D-*` id was left **null** by the seed).
Every endpoint expected a cuid. Consequences before the fix:

1. **Role-scoped strips ignored geo entirely** — Director/RVP/`/analytics` showed
   national numbers next to district-narrowed SSA tables (inconsistent page).
2. **`/schools` filtered client-side over a 200-row cap** — any district whose
   schools fell past row 200 was silently **under-counted** in both the list and
   the strip.
3. **SSA grids** applied geo client-side **only when grouped by district** — a
   selected district was ignored when grouped by region/cceo/cluster.
4. **Filter dropdowns were mock-sourced** — built from `schoolsMock`, so the bar
   offered the demo identity's mock portfolio, not the live backend districts;
   the active label couldn't resolve a backend-only district.

---

## D. The Fix

**Backend (one shared resolver, `analytics.service.geoWhere`)** — resolves the
FE's name/key into Prisma **relation filters** (`district: { name }`,
`region: { name: { equals, mode: 'insensitive' } }`, `clusterId`), ANDed within
the role scope. Threaded through: `dashboardSummary`, `leadershipSummary`,
`districtRollups`, `coverageSummary`, `schoolDirectorySummary`, `ssaPerformance`,
`activityPipeline`, `ssaPerformanceByGroup`, `interventionImprovement`,
`contribution`, and the `/schools` list. Country roles now also constrain
activities to the geo-narrowed school set (else the pipeline stayed national).

**Frontend** — `GeoFilterParams` + `appendGeo`/`geoQuery` thread the selection
through every analytics surface; `geoParamsFromSelection(selection)` maps the URL
filters to backend params; proxy routes + the SSA/Improvement client grids
forward `region`/`district`/`cluster` so **every grouping** narrows server-side.
Pages wired: `/analytics`, `/schools` (SchoolsHeader), Director + RVP
(DashboardPageHeader), `CountryAnalyticsLive`.

**Filter dropdowns → live data** — `getFilterScope({ liveDistrictNames })` builds
the geography options from `/analytics/districts` (role-scoped). The bar now
offers exactly the districts that exist in the data, the region→district cascade
resolves against real options, and the active label reflects the URL. Mock
fallback is preserved when the backend is off.

---

## E. Live Reconciliation (vs psql ground truth)

Ground truth: 700 schools, 50/district, regions Central 180 / Eastern 170 /
Northern 180 / Western 170.

| Probe | No filter | Filtered | ✓ |
|---|---|---|---|
| `dashboard` schools | 700 | `?district=Gulu` → **50** | ✅ |
| `dashboard` core | 234 | `?district=Gulu` → **17** | ✅ |
| `dashboard` region (case) | 700 | `?region=northern` → **180** | ✅ insensitive |
| `leadership-summary` | 700 / avg 6.2 | `?district=Mbale` → **50 / avg 5.9** | ✅ |
| `districts` rollup | 16 | `?region=eastern` → **4, all Eastern** | ✅ |
| `/schools` list total | 700 (200 shown) | `?district=Gulu` → **50, all 50 returned** | ✅ no 200-cap undercount |
| `contribution-summary` | 700 in scope | `?district=Gulu` → **50**, `?region=eastern` → **170** | ✅ |
| activity-pipeline | (clean DB 0) | `?district=Gulu` → 0 | ✅ |

**Browser (preview, Live · backend API):** `/schools?district=Gulu` strip
700→**50** (client 33, core 17); `/analytics?district=Gulu` contribution
"**50 schools in your scope**"; the district button now reads **"Gulu"** with a
Reset chip (was stuck on "All Districts").

---

## F. Tests

- `edify-api/.../geo-filter.spec.ts` (9): name→relation mapping, region
  case-insensitivity, `__all__` sentinel handling, and the **narrow-only**
  guarantee (never emits `id`; composes with an id-scope by AND).
- `edify-web/tests/apply-filters.test.ts` (+4): `geoParamsFromSelection` drops
  `__all__`, passes real geo, ignores non-geo selections (fy/cceo/ssa).
- Suites: **api 136 passed · web 594 passed**, both typecheck + build clean.

---

## G. Coverage Matrix (by filter)

| Filter | Reaches backend? | Whole page? | Notes |
|---|---|---|---|
| Region | ✅ (case-insensitive name) | ✅ | cascades to districts |
| District | ✅ (relation by name) | ✅ | flagship `/schools` + analytics + contribution |
| Cluster | ✅ (`clusterId`) | ✅ | grids + summaries |
| FY / Quarter | ✅ (already) | ✅ | period engine, unchanged |
| School type / SSA group / intervention / delivery | ✅ (already) | ✅ | grouped endpoints |
| People (CCEO / staff / partner / lens) | ✅ (already) | ✅ | scope-enforced; team lens 403-gated |

---

## H. Remaining (P2 — not blockers)

- **Mock-identity vs live-identity overlap.** The fix sources dropdowns from live
  districts; if a demo session's mock staffId differs from its live backend
  account, only the *option list* was ever affected — now corrected. Fully
  retiring `schoolsMock` from `getFilterScope` (counts in captions are still
  mock-derived) is the broader mock-purge migration item.
- **`/fy/ssa-comparison`** has a filter-aware engine but no filter bar (renders
  all districts for the FY) — a missed capability, not an inconsistency.
- **`/districts`, `/coverage`, `/quality-checks`, `/budget`** have no filter bar,
  so no "ignored filter" bug; their endpoints now accept geo if a bar is added.
- **Planning gap rows** carry no district yet, so the existing client geo scope is
  a no-op there — add district to the planning gap surface to activate it.

---

## I. Recommendation

**Geography filtering is ready for online testing.** The promise holds where it
matters most — the directory, the leadership cockpits, and analytics — verified
live against the database. Role scope is provably narrow-only. The remaining
items are additive (more filter bars, fuller mock retirement), not correctness or
safety gaps.

Commits: api `7203ed7` · web `9b6614c` (pushed).
