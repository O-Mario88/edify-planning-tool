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

## 🔵 DESIGN DEBT — RESOLVED / RE-SCOPED (executed 2026-06)

1. **KPI-row consolidation — DONE (right-sized).** The "18 near-identical rows" was
   really one duplicated thing: each redeclared its own tone→{bg,fg,glow} maps + stagger,
   and most ignored the existing shared `Tile`. The rows themselves legitimately differ
   (rings, sparklines, flat stat-bar), so a single mega-component would be *wrong*. Built
   `src/components/ui/kpi-tokens.ts` (one source for tones, with dark/glass variants),
   extended `Tile` (unit/delta/accessory, opt-in), migrated FundApprovals + CountryFund
   fully onto `Tile`, and switched LeadWeekly/Accountant/CceoSix onto the shared tokens.
2. **Color-token migration — NOT WARRANTED (measured).** Both `.dark` and `.glass` have
   their own ~316-rule auto-flip blocks in globals.css that already remap `bg-white` /
   `text-slate-*` / colored backgrounds. Verified all three themes across dashboards,
   tables, forms and charts — they render correctly. A 300-file migration would duplicate
   or conflict with that layer. The one true gap (colored *text*, which the flip skips)
   was fixed at the source: `Pill` + `EmptyState` got dark: variants.
3. **Card-style unification** — still open; lower priority, safe to defer.

---

### Net effect of this pass
- **−91 files**, no feature lost, build green, tests green, `tsc` 70 → 19.
- A clear **one-entity-one-source** map for the backend (the table above).
- A short list of **product-scope decisions** that are yours to make, not mine.
