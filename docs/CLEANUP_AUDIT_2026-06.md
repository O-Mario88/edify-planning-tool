# Pre-Backend Cleanup Audit — June 2026

Comprehensive sweep of the **frontend** (pages, data layer, design layer) ahead of
backend work. Goal: shrink the surface area and remove anything duplicate, obsolete,
or off-vision so the backend maps onto a clean, single-source-of-truth frontend.

Method: deterministic dead-code analysis (import-graph + word-boundary identifier
scan) cross-checked against a full `next build` (which catches `require()`-based
dynamic imports that `tsc` misses), plus three parallel semantic audits (routes,
data, design).

---

## ✅ DONE — removed this pass (91 files, build-verified)

Deleted every component/lib/mock reachable from **no route**. Verified: `next build`
compiles, 566/566 tests pass, `tsc` errors dropped **70 → 19** (the dead files
carried 51 of the pre-existing type errors).

| Group | What | Why dead |
|---|---|---|
| Orphaned heroes | `CceoWhatChangedHero`, `CceoOperatingHero`, `SsaHero`, `DecisionHero`, `PlanningGapsHero`, `CoreWhatChangedHero`, `PartnerTodayHero`, `SpHeroBanner`, … | Left behind by an earlier "global hero removal pass"; routes only mention them in stale comments |
| Shelved "billion" design | `my-targets/billion/*`, `team-targets/billion/*` | Abandoned design direction; 0 imports |
| Orphaned KPI/quick-action cards | `*KpiRow`/`*KpiStrip`/`*QuickActions`/`PlannedActivitiesCard` across cceo, core-schools, planning, team-targets, work-plan, partner, ssa, field-intelligence | Superseded by current dashboard compositions |
| Dead mobile views | `HomeView`, `TodayView`, `CplHomeView`, `CplApprovalsView`, `AccountantMobileView`, desktop-variants | Replaced by `ResponsiveDashboard` tree |
| Dead mock data | `work-plan-mock`, `core-schools-mock`, `messages-mock`, `mock-data`, `planning/gap-mock` | No live importer |
| Dead actions/libs | `leave-actions`, `portfolio-verification-actions`, `impact-actions`, `smart-digest`, `google-maps`, `partner-joint-work`, `partner-verification` | No live caller |

> One file (`lib/infra/dispatch.ts`) was flagged dead by static analysis but is loaded
> via `require("@/lib/infra/dispatch")` in `audit.ts` — caught by the build and **kept**.

---

## 🔑 BACKEND-CRITICAL — one canonical source of truth per entity

This is the single most useful output for backend design. Today several mocks describe
the same entity; the backend needs **one table/service per entity**, with the others
becoming *derived views*, not separate stores.

| Entity | Canonical (keep) | Make derived / retire | Notes |
|---|---|---|---|
| **Schools** | `schools-mock.ts` (Salesforce-aligned; 36 importers; access-control source of truth) | `core-schools-mock` (deleted), `core-school-replica-mock` (display-only KPI snapshot) | Core-schools should be a **query/view** over schools + activity, not its own table. Replica = dashboard KPI projection only. |
| **School IDs** | Salesforce numeric ids in `schools-mock` | partner `SCH-*`, planning `GAP-*` are scope-local | Backend needs a reconciliation mapping back to the canonical id. Add a test. |
| **District IDs** | `UG-D-*` in `lib/geography` (136 districts) | legacy `DST-*` in partner-mock (already aliased via `resolveDistrictId()`) | Standardize all new data on `UG-D-*`. |
| **Targets** | `team-targets-mock` (team) + `operating-targets-mock` (CCEO/PL scorecard engine) | confirm `my-targets-billion-mock` is just the personal projection of the same engine | Don't model targets twice; one engine, two scopes (team vs me). |
| **Fund approvals** | `fund-approvals-mock` (PL), `rvp-fund-approvals-mock` (RVP), `country-fund-approvals-mock` (CD) | these are **legitimately role-scoped** queues of the same underlying request | Backend: one `fund_request` table, three role-filtered views — not three tables. |
| **Planning gaps** | `planning/planning-gaps-mock` + `planning/gap engine` | — | Single gap engine; keep. |
| **Staff/Users** | `STF-<initials>-<n>` scheme, consistent | partner users `U-PA-*` etc. intentional | Coherent already. |

---

## 🟡 PRODUCT DECISIONS — RESOLVED (executed 2026-06)

| Surface | Route | Decision | Action taken |
|---|---|---|---|
| **Leaderboard** | `/leaderboard` | **Retire** | Removed route + 6 components + mobile view + the team-targets "Leaderboard" tab + all nav entries. Repointed inbound links by intent: champion-pipeline → `/core-schools`, recognition/gamification → `/team-targets`. Kept `calculateCategoryLeaderboard` (powers the login-hero stat). |
| **Field intelligence** | `/field-intelligence` | **Keep in full** | Discovered it's the daily-debrief + decisions backbone feeding ~10 live surfaces (`/decisions`, `/debriefs`, weekly reports, HR/RVP/Director dashboards). Not an edge feature — left untouched. |
| **Meta pages** | `/changelog`, `/activity-log` | **Retire** | Removed both routes; repointed activity-log links → canonical `/admin/audit-log`; dropped the data-intake "see related activity" step. |
| Leave management | `/leave` | **Keep** | Left in place. |
| Special projects | `/special-projects` | **Keep** | Left in place. |

---

## 🟢 KEEP — intentional, not cruft (audited and cleared)

- **Redirect-only pages** (`/`, `/dashboard`, `/m`, `/work-plan`→cceo, `/field-analytics`→analytics, `/data-upload`→data-intake/upload, `/dashboards/partner/*`→`/partner/*`): cheap backward-compat that protects bookmarks and documents migrations. Remove only after backend launch if you re-map URLs.
- **`/demo-guide`**: your sales-demo scaffold — an asset while you're presenting, keep.
- **`core-schools/replica/*`**: "replica" = the executive-cockpit *design reference*, **live and canonical**, not stale.
- **Demo seeding** (`seedDemoStore`, `demo-seed-actions`): correctly isolated (test-guarded / admin-only). Port `seedDemoStore` to a Prisma seed script and drop it from the hot path when real data lands.

---

## 🔵 DESIGN DEBT — recommend AFTER backend, not now (large, regression-prone refactors)

Not deletions — these are sweeping refactors that risk visual regressions across 100+
pages right before backend work. Track as separate efforts:

1. **KPI-row consolidation**: ~18 near-identical `*KpiRow` components → one parameterized `<KpiRow>` with role props. High value, ~15 files touched.
2. **Color-token migration**: ~300 files use hardcoded `text-slate-*`/`bg-white`. **Caveat:** globals.css already has `.dark`/`.glass` auto-flip rules remapping many of these, so the real breakage set is far smaller than a raw grep suggests. Migrate UI primitives first (`Button`, `Input`, `Tile`, `Pill`, `EmptyState`), measure in dark/glass, then decide if the long tail is worth it.
3. **Card-style unification**: `.card` / `.premium-card` / `.premium-glass` + 80 domain `*Card` components → one set of card mixins.

---

### Net effect of this pass
- **−91 files**, no feature lost, build green, tests green, `tsc` 70 → 19.
- A clear **one-entity-one-source** map for the backend (the table above).
- A short list of **product-scope decisions** that are yours to make, not mine.
