# Frontend performance report

## Measured final freeze routes

| Route | Browser duration | DOM nodes | Horizontal overflow |
|---|---:|---:|---|
| `/core-schools/champion-candidates` | 497 ms | 1,211 | No |
| `/activities/closure/blocked` | 506 ms | 1,335 | No |
| `/core-school-health` | 769 ms | 1,390 | No |
| `/planning/schedule` | 679 ms | 1,232 | No |
| `/ssa/manual/` | 207 ms | 1,254 | No |
| `/strategic-priorities` | 427 ms | 2,555 | No |

The final full authenticated browser crawl applies a 10,000-node general page ceiling and found no status, overflow, accessible-name, console, or page errors. The six freeze targets use a stricter 5,000-node and 8-second ceiling.

## Changes

- Replaced two full-school client selectors with bounded, permission-scoped HTMX search endpoints.
- Added server pagination to large queues, matrices, health pages, and milestone forms.
- Preserved shared design tokens; rebuilt Tailwind CSS and regenerated card/KPI inventories.
- Added Playwright release gates and retained traces/screenshots/video on failure.
- The existing service worker is release-versioned from the static manifest or release SHA, served at `/sw.js` with no-cache, and excludes API/authenticated document caching under existing tests.

## Browser result

The local matrix completed with 27 executed tests passing and 75 intentionally skipped combinations. Authenticated role crawling is deliberately run once in Chromium; public login/health and freeze regression run across all six configured profiles.

## Not measured

- Field RUM p75 LCP, INP, and CLS.
- Browser heap stabilization after 50 repeated HTMX/chart navigations.
- Event-listener and Alpine watcher counts over time.
- HAR files for every page family and production asset-cache/compression behavior.
- A two-release service-worker upgrade in actual deployed infrastructure.
- Native Edge and physical-device CPU/memory behavior.

These omissions prevent a general claim that all frontend performance gates pass.
