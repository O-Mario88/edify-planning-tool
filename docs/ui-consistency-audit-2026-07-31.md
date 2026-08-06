# Edify frontend deep audit and normalization — 31 July 2026

Status: **implementation complete; full-suite verified.**

This report records the repository state produced by the frontend audit. It is
paired with the generated route-level evidence in
`docs/platform-page-inventory.json`, the readable route catalogue in
`docs/platform-page-inventory.md`, and the metric catalogue in
`docs/platform-kpi-inventory.json`.

## 1. Audited surface

The inventory is generated from Django's live URL resolver, RBAC metadata,
navigation, view source, templates, tests, jobs, and activity states rather
than from a hand-maintained page list.

| Inventory dimension | Result |
|---|---:|
| Routed product surfaces | 470 |
| Registered routes | 870 |
| API routes | 292 |
| Roles | 11 |
| Permission keys | 66 |
| Full pages | 315 |
| Partials and drawers | 142 |
| Shared component templates | 285 |
| Permission-gated surfaces | 461 |
| Surfaces referenced by automated tests | 436 |
| Automated frontend findings | **0 critical · 0 high · 0 medium · 0 low** |

The inventory records route, page purpose, role access, permission key,
backend view, models/services, templates, HTMX/API endpoints, tables, forms,
charts, drawers, modals, state coverage, theme/responsive state, test status,
and automated score for each routed surface.

## 2. Canonical design-system contract

The normalized platform contract is now:

- Geist Sans is the sole product typeface. Google Fonts, CSS tokens, chart defaults,
  printable help exports, tests, and the compiled bundle all agree.
- Radius tiers are exactly 12px for surfaces, 8px for controls, and 16px for
  overlays through `rounded-surface`, `rounded-control`, and
  `rounded-overlay`.
- Light, blue, dark, and System themes share semantic tokens. System uses
  `prefers-color-scheme` and responds to live OS changes rather than guessing
  from the time of day.
- Opaque `bg-white` surfaces and raw hexadecimal colors were removed from all
  templates. Theme-aware surfaces now use `edify-surface` or a semantic token;
  translucent white remains only as an intentional inverse-surface overlay.
- Browser chrome theme color is resolved from `--edify-bg` after theme tokens
  load. Printable standalone documents import the design system rather than
  maintaining a private palette.
- Page headers carry the canonical `edify-page-header` marker. Legacy hook
  names may remain temporarily for stylesheet compatibility, but they no
  longer create a second header contract.
- Messages precede Notifications in the shared top bar. Search remains the
  single persistent global search surface.

Source-wide enforcement now finds no design-system violations in any template,
including templates that are not currently routed. That gate covers dead
links, inline browser handlers, hard-coded chart series, emoji icons, text
below the readable scale, opaque white theme leaks, raw colors, static inline
presentation, and unconditional fixed widths. The detector distinguishes real
CSS hex colors from HTMX fragment IDs and literal `style` attributes from
Alpine `:style` bindings; regression tests cover both edge cases. Every
template also compiles successfully through Django's template engine.

## 3. Shared primitives and KPI governance

Repeated KPI markup was migrated to `components/kpi_strip.html` across project
analytics, project planning, My Plan, team targets, HR, partners, SSA,
impact, Admin Operations, and country dashboards. The component accepts the
canonical registry payload and one presentation-only tone/helper adapter.

The SSA, Impact, Partner, country-health, Admin Operations, and IA strips now
carry stable metric identities from `apps.core.metrics`. Their registry entries
declare:

- the user decision supported;
- owning service and source models;
- numerator and, for percentages, denominator;
- date basis, period, scope, owner page, and filter behaviour;
- finance stage for money;
- drill-down destination and refresh semantics.

Missing SSA/impact evidence renders an explicit data state instead of a fake
zero. The `Team plans: Open` tile was removed because it was a navigation CTA,
not a measurable KPI. The hand-built KPI ratchet improved from 272 to 268 while
the normalized strips became fully registry-backed. Cross-module same-label
entries remain catalogue review candidates, not duplicate cards on one page;
the shared strip rejects same-strip registry duplicates.

Legacy template KPI family markers covered by the migration are absent from
product markup. Their old CSS selectors may remain only as inert compatibility
code until the stylesheet cleanup is separated from active user changes.

## 4. Impact Analyst workspace

### Navigation and information architecture

The IA workspace exposes one role-specific ten-section journey:

1. Dashboard
2. Activity Verification
3. SSA Verification
4. Unmatched SSA
5. Evidence Review
6. Data Quality
7. Core Verification
8. Impact Readiness
9. IA Analytics
10. Reports

The routes are permission-backed and the same workspace vocabulary is used by
the sidebar, page headers, route tests, and direct links.

### Dashboard

The bespoke IA hero, button family, and metric cards were removed. The page now
uses the canonical header, shared buttons, and one six-card registered KPI
strip answering six distinct operational questions: awaiting verification,
evidence ready, Salesforce ID pending, returned for correction, unmatched SSA,
and verification overdue.

### Activity Verification queue

- Queue ordering is critical/high risk first, then overdue, then oldest.
- The canonical desktop columns are activity, school, CCEO, partner,
  intervention, scheduled date, risk, evidence, Salesforce ID, and next
  action.
- One Review action is visible; secondary actions live in overflow.
- Native FY, status, risk, district, evidence, Salesforce, activity-type, and
  age controls retain state and push the URL.
- FY values use the stored four-digit contract; the old `FY25` mismatch that
  silently returned zero rows is gone.
- Each control has one accessible label. The mobile advanced-filter dialog is
  full-screen and the queue changes from a table to record cards rather than
  compressing columns.
- Empty states distinguish an empty queue from filters with no matches.

### Review workspace

- A record-specific h1 restores a valid document outline.
- Desktop is a three-pane summary/evidence/checklist workspace.
- Evidence, SSA, and attendance are real ARIA tabs with keyboard and URL state.
- Summary includes School, District, Cluster, CCEO/owner, Partner,
  Intervention, dates, Salesforce Activity ID with Copy, purpose, duplicate
  risk, previous returns, audit count, and finance routing.
- Return reasons are a fieldset with an explicit legend and labelled comments.
- The return dialog is a full-screen mobile sheet; focus enters the first
  reason and returns to the actual trigger when closed.
- Clear Activity and Return remain fixed at the bottom on phone/tablet and
  sticky beside the checklist on desktop. Both visual placements target the
  same canonical forms and therefore do not duplicate workflow logic.

## 5. Runtime defects found during visual QA

Browser QA found and fixed two defects that structural tests did not expose:

1. The shared back-link partial placed a top-level `try` statement directly in
   `x-init`. Alpine parsed it as an expression and raised `Unexpected token
   'try'` on every page using that primitive. The guarded code now runs inside
   an expression-safe IIFE; a fresh navigation adds no Alpine error.
2. The client-defect beacon read only the CSRF cookie. Deployments protecting
   that cookie with HttpOnly sent a zero-length token, so the report itself
   received a 403. The request-scoped 64-character token is now exposed through
   a same-origin meta tag and used as the safe fallback.

## 6. Responsive, theme, and accessibility evidence

Authenticated browser checks covered 390×844, 768×1024, and 1440×900.

- All ten IA destinations render with the expected h1 at desktop and
  mobile widths.
- Every checked IA destination has `documentElement.scrollWidth ===
  window.innerWidth`; no page-level horizontal overflow was found.
- The review workspace was captured in light and dark themes at desktop and in
  stacked tablet/mobile layouts.
- Messages and Notifications have the intended semantic order.
- The mobile verification queue renders cards and its filter dialog presents
  labelled native controls.
- The review DOM exposes one h1, labelled regions, a three-tab tablist,
  labelled checkboxes, a named dialog, a reason group, labelled comments, and
  reachable Clear/Return decisions.
- Reduced-motion, focus-visible, minimum-target, table-label, form-label,
  single-main, page-title, and missing-state contracts remain enforced by the
  repository quality tests.
- Runtime inspection confirms the IA, SSA, and Partner strips emit their
  registered `data-metric-key` identities. The shared shell resolves Geist Sans and
  exposes the request-specific 64-character CSRF token. The final authenticated
  route matrix added zero console errors.

The full route crawl supplies the broad role/route safety matrix; browser QA is
focused on the IA journey and shared-shell primitives where this change made
the highest-risk visual and interaction changes. No claim is made that 470
screens were each manually screenshot.

## 7. Verification gates

Completed gates:

- `npm run build:css`
- `python manage.py check`
- source-wide template scan: zero findings across every template
- source-wide Django template compilation: zero errors
- generated 470-surface inventory: 0 findings at every severity
- `git diff --check`
- Ruff on all changed Python audit/metric/view files
- KPI registry, definition uniqueness, strip migration: 63 tests + 946 subtests
- SSA, Impact, Partner, dashboard, KPI inventory: 52 tests + 780 subtests
- IA, theme, navigation, header, page inventory, UI quality: 58 tests + 877 subtests
- authenticated IA route matrix at desktop/mobile, plus review at tablet
- light/dark browser rendering and console-error follow-up
- repository-wide pytest: **3,524 passed, 2 skipped, 2,638 subtests passed,
  0 failed** in 47:05

The non-failing warnings are existing Django 6 constraint deprecation,
Memcached key portability, and naive-datetime test-fixture warnings; none is a
frontend failure or an ignored test.

## 8. Implementation map

The audit changed the shared system first and then migrated product surfaces
onto it. The principal implementation groups are:

- design tokens and enforcement: `static/css/design-system.css`,
  `static/css/consistency.css`, `static/css/components.css`, Tailwind source and
  compiled bundle;
- shell and shared primitives: `templates/base.html`, authenticated shell,
  topbar, sidebar, Page Header, KPI strip, buttons, forms, tables, tabs,
  drawers, dialogs, empty states, and back-link partials;
- IA command center: IA navigation, dashboard, verification queue, review
  workspace, filter dialog, mobile cards, SSA/evidence/data-quality/core/
  impact/analytics/report destinations, and their view/query contracts;
- metric governance: `apps/core/metrics`, SSA/Impact/Partner/country/Admin view
  payloads, the KPI source inventory, and its regression ratchets;
- platform coverage: normalized page headers, KPI strips, static styles, theme
  surfaces, control geometry, and responsive wrappers across the template tree;
- living evidence: `apps/system_health/page_inventory.py`, its command and
  tests, plus the generated page and KPI inventories paired with this report.

The repository was already a large dirty worktree when this pass began, so the
report groups changes by product contract instead of claiming unrelated local
edits as audit work.

## 9. Final disposition

There are no open automated frontend findings and no unresolved runtime defect
found by the audited IA browser journey. The generated inventories and
ratcheting tests are the CI enforcement mechanism: a new raw theme leak,
unregistered normalized-strip tile, duplicate same-strip metric, missing
canonical header, broken IA route, or new inventory finding fails the suite
instead of becoming another design exception.
