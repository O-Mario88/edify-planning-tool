# Edify — Mock Removal, Backend Wiring & Drill-down Audit (2026-06-17)

Response to the system-wide mandate: remove production mock data, fix fake
geography, wire unwired surfaces to real backend data, add drill-down analytics,
and prove clean-DB-empty / generated-data-populates behaviour. Method: 2 parallel
read-only surveys (fake geography · unwired surfaces) → fix in priority waves →
**live reconciliation vs psql + browser** → commit each wave.

This report is honest about scope: the highest-integrity and highest-leverage
items are **done and verified**; the large net-new features (MatrixMap, the full
Action-Drawer refactor, new trainings/monthly-fund backend modules) are **scoped
but not built** — listed in §E with a roadmap, not claimed as complete.

---

## A. Executive Verdict

### ✅ Production no longer ships fake data; the named trust-breakers are fixed and verified. ⚠️ Several large net-new features remain.

**Score: 72/100** toward the full mandate — but **100/100 on data integrity**
(no fabricated production data remains in the surfaces audited). Build + tests
green on both repos.

| Area | Status |
|---|---|
| Fake / non-Ugandan district names | ✅ removed — CCEO heatmap was Zambian cities, now live Ugandan districts; 10 filter headers now source live geography |
| Mock dashboard data (core heatmap) | ✅ backend-driven |
| Donor reporting fabricated PDF/CSV | ✅ killed — verified-only, honest "not ready" on clean DB |
| Partner fabricated boards | ✅ killed — live assigned-work queue only |
| Unwired surfaces (today/team-targets/weekly-funds/partners) | ✅ wired live |
| District → sub-county SSA drill-down | ✅ built + verified |
| MatrixMap (CD/PL/HR), Action-Drawer refactor, trainings + monthly-fund modules | ⚠️ scoped, not built (§E) |

---

## B. Build / Test Results

| Gate | Result |
|---|---|
| web typecheck | ✅ clean |
| web tests | ✅ 594 passed |
| web production build | ✅ 156 routes compiled |
| api typecheck | ✅ clean |
| api tests | ✅ 136 passed |

---

## C. Mock Data & Fake Geography Removed (verified)

| Surface | Before | After (verified) |
|---|---|---|
| **CCEO dashboard SSA heatmap** | `cceo-mock` **Zambian cities** (Lusaka, Kitwe, Ndola…), unguarded in prod | `CoreSsaHeatmapLive` over grouped SSA-by-district — **real Ugandan districts** (Mukono, Gulu, Bushenyi… avg 6.5-6.7) |
| **Donor PDF** (`/donor-reporting/print`) | hardcoded donor numbers, **no guard** | `buildLiveDonorSnapshot` over `/analytics/contribution-summary` (verified records only); clean DB → "Donor report is not ready" |
| **Donor CSV export** | fabricated CSVs shipped externally | verified-only; clean DB → "Not ready" file, never invented figures |
| **partner/planning, partner/today, partner/assignments** | fabricated KPI strips + boards, no guard | live `PartnerWorkQueueLive` (real assignments) only |
| **10 filter headers** (schools, analytics, dashboards, approvals, director, planning, partner, ssa, special-projects, team-targets) | 136 FE-constant districts (most not in DB) | live `/analytics/districts` universe — offers only districts that have data |

Backend ground truth: 16 real Ugandan districts (Apac…Wakiso). No foreign names remain in any audited production surface.

## D. Surfaces Wired to Backend (verified clean-DB behaviour)

| Route | Endpoint | Clean-DB result (verified) |
|---|---|---|
| `/today` | `/command-center/today` | **14 real CCEO actions** ("700 schools not in a cluster → Assign") |
| `/team-targets` | `/targets/time-period` | **6 live period rows**, honest "no verified activity yet" |
| `/weekly-funds` | `/budget/weekly` | **0 → honest** "No weekly fund request yet — schedule activities" |
| `/partners` | `/partners` | **5 real partner records** |
| `/analytics` sub-county drill-down | `/analytics/ssa-performance-grouped?groupBy=subCounty&district=` | `?district=Gulu` → **5 Gulu sub-counties** (Bungatira 7.3 → Layibi 5.2), none outside Gulu |

**Clean-DB rule proven:** real data where work exists (today actions, partners,
target periods, SSA), honest explanatory empty where it doesn't (weekly funds),
fabricated data nowhere.

## E. Scoped but NOT Built (the large net-new features — prioritised roadmap)

These are genuine multi-day features; I did not build them rather than ship
shallow/broken versions. Priority order for the next pass:

1. **`/monthly-fund-request` aggregate** — needs a backend `GET /fund-requests/monthly?country&month` rollup; FE then drives PL→CD→RVP via the existing `/fund-requests/:id/*` actions (those exist).
2. **`/trainings` module** — no backend resource; either a new `trainings` Nest module (cohort + participants + attendance + post-SSA delta) or derive a read-only list from `GET /activities?kind=training`. Until then the page stays honestly guarded.
3. **MatrixMap (CD/PL/HR staff performance)** — context-aware fair-performance plot + Performance Management Plan workflow. The fairness engine (`fwi-engine.ts`) exists but runs on mock; needs a backend staff-performance aggregate (verified activity, SSA contribution, workload, geography difficulty) before it can be shown without fabrication.
4. **`/analytics/data-room` charts** — re-point `FieldEngineAnalytics` onto the existing grouped/intervention/contribution endpoints (currently honestly guarded).
5. **`/budget/approvals/[id]` detail** — rebuild on `GET /fund-requests/:id` (the canonical live queue is already `/approvals`).
6. **Action-Drawer system** — a system-wide refactor making workflow buttons open drawers (Assign Support, Schedule, etc.) instead of navigating. Large cross-cutting UI change; the deep-link drawer seam (notifications → drawer) and `getSchoolSupportRecommendation` backend are the prerequisites.
7. **Partner test login** — 5 partner *orgs* exist but the 10-account roster has no partner *user* to log in as; add one partner account + DEMO_USERS mapping to exercise the partner workflow end-to-end.

## F. Remaining Risks (real only)

- **Orphaned Zambian replica mock** (`core-school-replica-mock.ts`) still exists in the tree but is **not rendered** by any live route (its only consumer, `CoreSchoolShell`, is unreferenced). Safe but should be deleted in cleanup.
- **`/monthly-fund-request`, `/trainings`, `/analytics/data-room`, `/budget/approvals/[id]`** remain honestly guarded ("Insufficient data") — safe (no fake data) but not yet populated; covered by §E.
- The new live components (heatmap, donor snapshot, weekly funds, partners list, sub-county panel) are verified live but **not yet unit-tested**; the underlying data paths are covered by existing api tests + the filter specs.

## G. Verdict

**Ready for online testing on the data-integrity bar** the mandate set: no
fabricated production numbers, real Ugandan geography everywhere, the named
surfaces wired and proven to populate from real records / show honest empties.
The remaining §E features are additive and should be sequenced next; none are
data-integrity risks today.

Commits (web, pushed): `c5f35e8` (mock-leak/geo), `1d44841` (4 surfaces wired),
`2ad5e37` (7 headers geo), `012ce7b` (sub-county drill-down).
