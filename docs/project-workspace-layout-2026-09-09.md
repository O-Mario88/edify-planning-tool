# Project workspace layout rework — 9 September 2026

The project work queue now owns the available content width. Planning, My Plan,
and Project Analytics place supporting context below the main content instead of
compressing wide tables beside fixed-width side panels. The project portfolio
also gives its primary table the full workspace width.

## Layout contract

- Planning readiness guidance is an expandable section; the KPI strip and queue
  tabs retain the at-a-glance counts. Expanded guidance uses compact joined cells.
- My Plan keeps period, project and status filters together. Optional filters
  appear in a disclosure when their scoped dataset offers choices. Tablet fields
  use three columns, phone fields two, and desktop fields share the available row.
- Repeated period headings in My Plan tables are removed; the period remains in
  the navigation and accessible table captions. Mobile cell labels match their
  actual data columns.
- Participating schools use the shared paginated table and compact row actions.
- Project detail pages expose assignment forms on demand and place detailed
  project metadata and the leadership decision in a disclosure. The current
  status stays visible in the overview.
- School, cluster, partner and project profile workspaces use one content column
  from 1024px to 1599px, preventing their tables from losing a third of a laptop's
  already reduced workspace to a side panel.
- Project Analytics no longer embeds the unrelated country map ahead of project
  filters. Country geography remains on the home dashboards.

## Shared table fixes

The fitter only applies a column plan when it can actually fit. Impossible fits
retain the table's contained horizontal scroll region instead of overlapping
controls. Floating Alpine menus are excluded from plain-cell styling, and their
explicit hidden states take precedence over structural display rules. These
fixes apply to tables throughout the platform, including HTMX replacements.
Table actions use the named 12px micro typography token, and drawer relationship
styles use explicit structural markers instead of ancestor-sensitive selectors.

Theme tokens, fonts, KPI values, role permissions, exports, filter names, and
form actions are retained. Shared asset cache keys are advanced together.

## Verification

- Design-system, typography, mobile-density and platform-layout source contracts:
  92 passed. JavaScript syntax and Django system checks passed.
- Project browser suite: 9 tests passed across Chromium, Firefox and WebKit,
  covering five routes, five viewports (390, 768, 1280, 1366 and 1920px), and
  light, dark and blue themes. Filters, HTMX tabs, disclosures and row menus are
  exercised without submitting operational forms.
- Final project rerun after the participating-school table and filter-toggle
  updates: all 9 tests passed again across the three browser engines. Screenshots
  disable transitions so theme captures reflect settled colors.
- Filter containment: 162 saved role/page layouts, five widths, 810 checks,
  no overlaps or escaping controls.
- Plain table content: 90 saved pages, two widths and three themes, 540 checks,
  no unexpected borders or highlights on non-action content.
- Live CCEO/Admin landscape checks: 144 viewport/theme states across 19
  role/route combinations. Finance status, partner queues, HTMX filters and
  inserted table content also passed.
- The first scheduling-drawer check started before the restarted local server
  was ready and received a connection-refused error. Its isolated rerun passed
  for scheduling, nested visit scheduling, assignment and cluster creation at
  five widths. The leave drawer also passed. No checks remain unresolved.
- KPI inventory regenerated: 142 shared summary surfaces, no legacy summary
  surfaces, and no changes to metric definitions or values.

At 1366×768, Planning's table moved from approximately 684px down the page to
544px, and My Plan's filter area fell from about 160px to 82px. These are local
fixture measurements, not guarantees for every dataset or translated label.

Saved-page checks exercise current shared assets against previously rendered
role-scoped HTML. Live checks supplement those with current templates and data;
they do not certify every possible production record, role state or workflow.
