# Freeze root-cause report

The reported freezing was reproduced locally as severe server/DOM work on high-volume pages. The primary confirmed defect was an N+1 query path; the remaining confirmed risks were unbounded rendering and browser selectors.

| ID | Route | Reproduction/root cause | Before | Fix | After | Regression |
|---|---|---|---:|---|---:|---|
| FRZ-001 | `/core-schools/champion-candidates` | Per-school eligibility queries and status saves across thousands of schools. | 23.538 s, more than 9,000 queries, 194,659-byte response | Batch all eligibility facts, compute statuses in memory, bulk-update changed rows. | Service 0.281 s / 5 queries; browser 497 ms / 1,211 DOM nodes | Query-scale test plus Playwright freeze gate |
| FRZ-002 | `/activities/closure/blocked` | Entire blocked closure queue rendered at once. | Unbounded row DOM | Server pagination | 506 ms / 1,335 DOM nodes | Pagination contract plus Playwright |
| FRZ-003 | `/ssa/manual/` | Approximately 16,988 schools embedded in one datalist. | Browser-heavy initial markup | Scoped HTMX autocomplete, 25-result cap | 207 ms / 1,254 DOM nodes | Lookup tests plus Playwright |
| FRZ-004 | `/planning/schedule` | Full school catalogue embedded in the scheduling form. | Browser-heavy select | Scoped HTMX autocomplete | 679 ms / 1,232 DOM nodes | Lookup tests plus Playwright |
| FRZ-005 | `/core-school-health` | Multiple operational lists rendered without independent bounds. | Unbounded rows | Independent pagination for stalled slots, plans, and districts | 769 ms / 1,390 DOM nodes | Pagination contract plus Playwright |
| FRZ-006 | `/strategic-priorities` | Every milestone rendered with complete definition/allocation forms. | About 2.4 s / 15,728 DOM nodes | Flattened rows and server pagination (10 rows) | 427 ms / 2,555 DOM nodes | Pagination contract plus Playwright |
| FRZ-007 | `/accounts/blocked` | More than 10,000 DOM nodes. | 10,123–10,827 DOM nodes | Paginated account rows | Below general 10,000-node gate in final role crawl | Authenticated browser crawl |
| FRZ-008 | `/admin-panel/page-access-matrix` | Full role-by-page matrix eagerly rendered. | 10,085 DOM nodes | Paginated both roles and pages | Below general 10,000-node gate in final role crawl | Authenticated browser crawl |

All six dedicated freeze-regression routes returned 200, remained within an 8-second ceiling, stayed under 5,000 DOM nodes, and had no horizontal overflow in the final Chromium run.

## Evidence not available

Production browser performance traces, server APM traces, CPU/memory history, `pg_stat_statements`, Redis keyspace telemetry, DigitalOcean instance metrics, and a real-user freeze recording were unavailable. The local root causes are confirmed; claiming that every possible production freeze has been eliminated would exceed the evidence.
