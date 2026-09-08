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
