# Calm workspace frontend rebuild

The platform now uses a quieter shared visual system: aligned page headings, compact controls, restrained surfaces and data-led layouts. Edify branding remains visible in navigation and actions. Light, dark and Edify Blue retain separate palettes.

## Platform scope

`ui-surface-inventory.json` enumerates all 231 page templates and their inheritance: 215 workspace pages, nine authentication/public pages, two print documents and five embedded fragments. Workspace pages use the shared shell and design tokens; public/authentication pages and print documents also load the design system. Embedded fragments inherit the containing page.

The implementation changes the shared sources instead of maintaining a separate redesign for every URL. Existing permissions, actions, financial calculations and role-specific content remain server-owned.

## Changes

- Page headings sit on the canvas, aligned with the content below. Removed header surfaces, large insets and decorative shadows across the shared header families.
- Cards use subtle borders and consistent gutters. Blue content surfaces are opaque, with a solid navy canvas replacing the photographic treatment.
- Geist remains the single interface font family. Mobile body text is 14px, form labels and table text are at least 13px under the compact mobile contract; secondary metadata remains smaller. KPI numerals remain 20–24px.
- All 140 identified KPI surfaces use the shared strip. Light strips are white, dark strips navy and Edify Blue strips blue. Metrics scroll within the strip on narrower layouts, preserving all values.
- Tabs use connected segments: sharp internal joins and curved outer ends. Short desktop tab groups fit their content instead of filling an empty track.
- Team Oversight places its period controls beside the title and groups team selection with filtering/export. Removed repeated selection descriptions. Right-aligned costs and preserved status acronyms.
- Analytics uses a simpler performance heading, one page wrapper and expandable data context/provenance. Supporting explanations remain accessible without occupying the default reading path.
- Read-only finance scope values share the form surface palette. Native disclosure actions follow the button contract.
- Public loan and agreement headings have less padding and more restrained typography. Reading content retains its document-oriented line height.

## Verification

The source inventory covers all 231 page templates. The browser sweep covers 1,280 successful full HTML page variants across all 14 roles at 390, 768 and 1600px in Light, Dark and Edify Blue: **11,520 checks, zero reported layout/typography issues**. Coverage is recorded in `ui-rebuild-verification-2026-09-08.json`.

The complete argument-free route crawl passed all eight tests. The final KPI and connected-tab suite passed all 72 tests in Chromium, Firefox and WebKit, including contrast, accessible names, keyboard/scroll navigation, long values, resizing and real HTMX replacement.

Final source verification covered 211 design, rendering and inventory tests. One stale landmark assertion was corrected to recognize the standalone offline page; the complete design-contract module then passed alongside the coordinator planning and export tests. Seven live browser checks passed across Chromium, Firefox and WebKit (the populated field workflow runs in Chromium only).

A live measurement at 1048px with the sidebar collapsed places Team Oversight’s first data row at **447px**, compared with about 710px before the rebuild. This is a reduction of roughly 37% in the vertical distance to the data on that screen.

Automated snapshots cover successful argument-free routes. Populated live checks separately cover finance, oversight, analytics, schools, a school record, planning, calendar and profile. This does not certify every possible record, permission transition, modal or production data state.

## Local environment repair

The populated school record initially returned HTTP 500 because the existing `activities.0052_schoolvisitfeedback` migration had not been applied to the local `edify_pm` database. The migration was reviewed (one additive table creation), applied locally, and the school-record check then passed. No new migration was written.

## Reproduce

Run browser suites sequentially on memory-constrained machines:

```sh
TEST_DATABASE_NAME=test_kpi_platform_20260908 .venv/bin/python manage.py test apps.frontend.test_route_crawl --keepdb --noinput
npx playwright test e2e/calm-platform.spec.js --project chromium-desktop --workers=1
npx playwright test e2e/kpi-strips.spec.js e2e/tab-corners.spec.js --project chromium-desktop --project firefox-desktop --project webkit-desktop --workers=1
npx playwright test e2e/calm-workspace.spec.js --project chromium-desktop --project firefox-desktop --project webkit-desktop --workers=1
```

The live suite uses the local seeded QA accounts and refuses to accept pending legal agreements automatically. The snapshot server is loopback-only, does not write data, and blocks external resources.

## Follow-up polish — 9 September

- Restored the blue login KPI surface, readable white headings on the blue brand panel, and a compact mobile/tablet layout that keeps sign-in and KPIs together.
- Removed Planning Copilot. Its missing-SSA and core-gap counts already exist in the shared strip; the distinct unclustered-school count now joins them without duplicating metrics.
- Converted Personal Time Off's summary and entitlement cards to shared strips while retaining allocation, usage, pending requests, coverage and availability values. Leave policy guidance remains expandable.
- Fixed the leave page's intrinsic grid sizing so mobile navigation cannot widen the page or KPI strips.
- Changed the light canvas to blue-grey `#e8eef5`, with 450-weight body/table text and 550-weight labels/identity cells using the existing Geist variable font.

The focused responsive suite covers login at 390, 768, 1048, 1290 and 1600px, and Planning/Personal Time Off at 390, 768, 1048 and 1600px in all three themes, including opening the leave request drawer. Regression test: `e2e/workspace-polish.spec.js`.

Verification passed in Chromium, Firefox and WebKit. The source/login/inventory suite covered 154 tests; its old canvas-colour assertion was updated and the complete 72-test design-quality module passed on rerun. Subtle text contrast on the new canvas is 4.74:1. The regenerated inventory identifies 142 shared strip surfaces.

## Plain table content and partner finance queues

Partner Payments now contains partner-delivered activities and partner invoices only; the embedded transport-provider queue was removed. Its existing payment records are preserved. Finance Approval History uses semantic status text instead of a black filled pill.

The shared table enhancer removes decorative borders, fills and shadows from cell content, including editable text fields. Status labels use readable theme colours, while action buttons keep their styling. Native selection controls, floating menus and keyboard focus remain functional. The same markers are applied after HTMX updates. Table grid lines and row/header fills now use one plain surface.

Regression coverage is in `e2e/plain-table-content.spec.js` and the partner queue tests in `apps/fund_requests/test_finance_operating.py`.

Plain-table verification: 528 settled layout checks across 88 rendered page variants; finance and dynamically inserted table content verified in Chromium, Firefox and WebKit; 18 queue/interactions tests and 114 shared-style/inventory tests passed.

### Compact school, cluster and table actions — 9 September

School record lists previously inherited the 40px page-action size, unlike condensed table controls. Record rows, legacy school cards, cluster cards and enhanced table actions now share a 24px height, 12px icons, 11px labels and 8px horizontal padding. The rule is scoped to records; page actions, drawer footers, disclosure overlays and floating menus retain their existing sizing. Theme colours, accessible names and HTMX actions are preserved.

Verification: the rendered-table sweep covers 88 page variants across three widths (390, 768, 1290) and three themes, checking height and vertical clipping. Live Schools, Core Schools and Clusters checks also cover those widths and themes, and exercise keyboard activation of the core-school scheduling drawer.

### Table header hierarchy and Accountant focus — 9 September

In Light mode, local table title bars use a blue background with white heading text. Column headings use the same blue ink while retaining their existing surface colour. Shared structural enhancement finds local title bars on initial render and HTMX refresh without changing page headings or filter forms. Dark and Blue theme treatments remain scoped separately.

The Accountant landing workspace now renders finance operations directly. The map tab, map partial and map asset include were removed; old map URLs, saved preferences and HTMX shell requests resolve to the operational queue. Other roles retain their maps. Regression checks cover the role behaviour, shared UI contracts, theme/viewport styling and browser rendering.

### Compact centred drawers — 9 September

Shared drawer widths now cap at 416/560/688/800/960px for small through workspace tiers. Desktop dialogs retain a viewport inset and scroll within a height cap; headers, body padding, close controls and footer shelves are tighter. Legacy workflow popups share the cap, and the separate leave drawer is centred on desktop. Cluster creation no longer overrides the phone inset. Scheduling choice labels and descriptions stack cleanly.

Browser regression coverage opens scheduling, the legacy core-visit form, assignment and cluster creation at 390/768/1290/1920px, checks centring and overflow, and closes each dialog. A separate check verifies desktop leave-dialog centring.

### Landscape map layout — 9 September

Desktop maps now use the viewport height available beneath the dashboard header instead of a width-driven square. The SVG preserves the full geographic extent, and the distribution panel sits alongside from 1024px with its own bounded list. Resizing recalculates the height. Short laptop screens show sub-region names in the national overview; district labels remain available in focused views and hover details. Browser checks cover 1024×768, 1280×720, 1366×768, 1440×900 and 1920×1080.
