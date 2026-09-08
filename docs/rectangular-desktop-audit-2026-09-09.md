# Rectangular desktop UI audit — 9 September 2026

The shared workspace was reviewed for short, wide laptops and larger desktop monitors. The audit checks the content area as well as the browser document: a page can have no document overflow while its independently scrolling workspace still clips controls.

## Adjustments

- Team Targets: allow long panel headings and the performance-status filter to wrap independently. “High risk” stays visible and usable in a narrow desktop workspace.
- Analytics: reduce the additional-metrics disclosure height on desktop viewports at or below 800px tall.
- Leave approvals: size the request queue against available viewport height, remove excessive padding from large empty states, and remove the orphan search icon left after search moved to the top bar.
- HR Today: show each empty queue as a compact heading/status row, removing the repeated empty message so active queues appear earlier.
- Partner Oversight: retain archived/missing partner history without linking to an unavailable live profile. This was found by following a populated record link, outside the argument-free route sweep.
- Preserve the existing font sizes, theme colours, table scroll regions and centred drawer width limits.

## Verification

- Argument-free route crawl: 3 tests passed, across all 14 roles.
- Full snapshot layout sweep: 1,087 role/route combinations, 3,261 checks across three desktop sizes, zero remaining layout findings (Chromium).
- Shared density and filter contracts: 23 tests passed. Updated stale assertions for the existing 40px page-action token and a superseded stylesheet cache key; no button dimensions were changed in this audit.

- Partner grouping/navigation regression: 5 tests passed, including active, archived and missing profiles with unchanged history/totals.
- Firefox and WebKit: all 6 drawer/map tests passed. Chromium scheduling/assignment/cluster/leave drawer tests also passed at phone, tablet and landscape desktop sizes.
- Populated live coverage: 186 measurements across six available accounts in all three themes, including mobile/tablet checks on the changed analytical and HR surfaces. The Admin pass and focused Leave Approvals/User Management rechecks passed after the final changes. Eight other accounts were blocked at onboarding, as detailed below.

## Coverage and interpretation

The route crawl renders successful argument-free routes for all 14 roles. Browser tests deduplicate trailing-slash aliases and examine each available full-page snapshot at 1280×720, 1366×768 and 1920×1080. These are role/route combinations, not distinct page templates. Snapshot rendering uses current local assets and blocks external requests; populated live navigation supplements it for data-dependent content and interactive controls.

The browser sweep checks document and workspace overflow, offscreen KPI strips/filter bars/page headings/tab rails, filter controls escaping their fields, and controls clipped by enclosing panels. It waits for chart redraws following viewport changes. A first-table-below-the-fold observation is reviewed rather than treated automatically as failure: analytics and leave pages intentionally show useful primary cards before supporting tables. Normal vertical scrolling remains available for long operational records; fitting all records into one screen would reduce readability.

Live checks were attempted with local seeded users from all 14 roles. Eight accounts were blocked by required safeguarding agreements: RVP, HR, Project Coordinator, both partner roles, Business Transformation and both MFI roles. Those agreements were not accepted or bypassed, and these live cases are recorded as blocked rather than passes. Their argument-free layouts remain covered by the successful all-role snapshot sweep. Available live accounts cover representative operational routes and discoverable record details in Light/Dark/Edify Blue; changed HR pages are additionally exercised through the authorized Admin account. Scheduling, assignment and cluster creation dialogs are opened, resized and closed without submitting forms. These checks do not certify every possible database record, permission transition or submission branch.

## Reproduce

Run the browser suites sequentially on memory-constrained machines:

```sh
.venv/bin/python manage.py test apps.frontend.test_route_crawl.RouteCrawlTest --keepdb --noinput
npx playwright test e2e/rectangle-platform.spec.js --project chromium-desktop --workers=1
npx playwright test e2e/rectangle-live.spec.js e2e/compact-drawers.spec.js --project chromium-desktop --workers=1
npx playwright test e2e/compact-drawers.spec.js e2e/landscape-map.spec.js --project firefox-desktop --project webkit-desktop --workers=1
```

Snapshot manifests are in `test-results/kpi-platform-crawl`; audit findings are in `test-results/rectangle-audit`; populated screenshots and measurements are in `test-results/rectangle-live`. `RECTANGLE_ALL_THEMES=1` expands the snapshot sweep to all three themes. Live tests refuse to accept pending agreements.
