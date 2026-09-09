# Platform KPI strip overhaul

All 140 identified KPI summaries use the shared context-metrics renderer, including role dashboards, operational pages, drawers, upload previews and public sign-in. The generated inventory is in `platform-kpi-inventory.json`. Table cells, chart legends and form fields retain their existing presentation.

The continuous strip uses white, dark navy or Edify blue surfaces according to the active theme. Container width controls the visible metrics: eight on wide layouts, four on tablet-sized containers and two on narrow containers. Overflow supports native scrolling, keyboard navigation and progressive range/progress controls. Existing links, filters and HTMX drilldowns are retained.

Values use 20–24px tabular text (22px on narrow containers), 10px vertical padding and 3px internal gaps. Currency values at one million and above use compact M/B/T notation; the exact amount remains in accessible text and the title. Labels and helper text remain 12px. No synthetic trends are introduced.

## Verification scope

- All platform templates compile; shared renderer tests cover zero/missing values, escaping, field scoping, currency accessibility and retained actions.
- The isolated database crawl covers all 14 platform roles and inspected 2,290 HTML responses, including 512 KPI-bearing full-page snapshots, with no metric DOM issues.
- Browser audits exercise the saved role/page snapshots across three widths and three themes. These snapshots use test data and cover argument-free routes; they do not represent every possible record-specific state.
- Component browser tests cover Chromium, Firefox and WebKit, responsive navigation, resizing, HTMX replacement, contrast, populated page fixtures and public sign-in.

Reproduce with the targeted frontend tests, `apps.frontend.test_route_crawl`, `apps.system_health.test_kpi_inventory`, `e2e/kpi-strips.spec.js` and `e2e/kpi-platform-pages.spec.js`. The page browser audit consumes snapshots written by the route crawl under `test-results/kpi-platform-crawl`.
