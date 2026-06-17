# Edify — KpiStrip Design-System Consolidation (2026-06-17)

Response to the "one premium KPI strip, system-wide" mandate. Goal: a single
canonical strip component replacing scattered metric tiles, with icons, tones,
backend-driven values, filter-awareness, responsive behaviour, and loading/
empty/error states.

## A. Component Created

**`src/components/ui/kpi-strip.tsx` → `KpiStrip`** — the canonical, only KPI surface.

Props (per spec): `title?`, `subtitle?`, `items: KpiStripItem[]`, `loading?`,
`error?` (+ `onRetry?`), `emptyMessage?`, `columns?`, `bare?`, `className?`.
`KpiStripItem`: `id, label, value, subValue?, icon? (ReactNode), tone?, subTone?,
tooltip?, href?, onClick?, active?`.

- **Visual**: rounded-2xl card, soft border/shadow, uppercase title + optional
  subtitle, segmented hairline cells (collapsing 1px borders → one continuous
  band), per-cell icon + uppercase label + large tabular value + optional
  sub-value. All design-token driven (light/dark/glass inherit).
- **Tones** (6): default/success/warning/danger/info/muted colour the value;
  an independent `subTone` colours the sub-value (so a trend delta keeps its own
  red/green while the value stays neutral).
- **States**: `loading` → skeleton cells; `error` → message + Retry; empty →
  "No records found for the selected filters." — **never a misleading zero**.
- **Interaction**: `href` (deep link) / `onClick` + `active` (filter cell).
- **A11y**: `aria-label` on the section, `aria-hidden` icons, `aria-pressed` on
  filter cells, `title` tooltips, semantic contrast (no colour-only meaning —
  every cell has a label + value).

## B. System-wide Consolidation (the key move)

The codebase already had `MetricStrip` rendered across ~30 surfaces (every role
dashboard, schools, planning, leave, funds, analytics…). Rather than churn 30
call sites, **`MetricStrip` is now a thin adapter over `KpiStrip`** — its
`metrics` map through `metricToKpiFields` (legacy tone → new tone, delta →
arrowed sub-value, unit formatting) into `KpiStripItem`s and render through the
one component. So **every existing strip instantly renders through KpiStrip** —
true single-design consolidation, zero regression (594 → 600 tests green).

| Surface | Before | After |
|---|---|---|
| All ~30 `MetricStrip` sites (dashboards, schools, planning, leave, funds, analytics, …) | MetricStrip's own render | render through **KpiStrip** (one design) |
| **School Directory "Portfolio at a glance"** (the reference screenshot) | MetricStrip, no icons | **KpiStrip directly via `DirectoryKpiStrip`** with per-cell icons |

## C. Icons (reference page)

`DirectoryKpiStrip` maps each metric key → a Lucide icon (server components can't
pass icon refs across the boundary, so this thin client wrapper does it):
Total→School, Client→Briefcase, Core→ShieldCheck, Clustered→Network,
Unclustered→MapPinOff, SSA Complete→CheckCircle2, SSA Pending→Clock.
**Verified live**: 7 icons rendered, values 700/466/234 (backend), tone colours
(unclustered danger, SSA-complete success).

## D. Backend-driven + filter-aware

The School Directory strip values come from the page's live backend fetch
(`aggregateDirectoryMetrics(/analytics/dashboard)`) and already narrow with the
geography filter (700 → 50 for `?district=Gulu`, proven in the filter-accuracy
pass). KpiStrip itself never computes or invents numbers — it renders what the
caller supplies and reflects loading/error/empty honestly.

## E. Tests

`tests/kpi-strip-adapter.test.ts` (6) locks the pure `metricToKpiFields` mapping:
tone map (alert→danger, good→success), delta→arrowed sub-value with independent
sub-tone, unit formatting (`62%`, `5 schools`), caption→sub-value, href/active
passthrough. (The repo's harness is pure-logic, not component-render — the
visual/icon behaviour is proven by live browser verification instead.)

## F. Remaining (honest)

The **page-level KPI strips are unified**. A small tail of **secondary/embedded
tile groups** remains and was deliberately not force-fit into a full-width strip:

- `TrainingCoverageCard` (2×4 `KpiCard` grid) — training data has no backend yet
  (trainings module is unbuilt); migrating it would mean wiring mock numbers.
- `PlanCascadeCards` (3 `StatTile` budget mini-summary **inside** a plan card),
  chart-internal stat cells (`CceoPerformanceTable`, `TeamPerformanceChart`),
  and mobile mock views (`RvpMobileView`, `PartnerSubPageHeader` KPIs — the
  latter already mock-gated) — these are embedded micro-summaries, not the
  page's primary KPI surface; a full strip doesn't fit a 3-cell in-card summary.
- `DonorReportingImpact` (`MetricCard`) — orphaned component, not rendered live.

Recommended next step if full coverage is required: add an icon-key map to each
page's metric builder and convert the embedded grids case-by-case; none are
data-integrity or layout risks today.

## Verdict

KpiStrip is now the system-wide metric language: one premium component, every
primary strip unified through it, the reference page migrated with icons,
backend-driven + filter-aware, with real loading/empty/error states. Build +
600 tests green. Commit `39aae75`.
