# Offline school GPS capture — performance and data-integrity test report

Branch `agent/native-build-batch`. All runs on this Mac against the local test database `edify_gorn_test` (seeded test data; never production). Local gateway, local OSRM. Figures are what was measured here, not projections. Brief and decisions: `next-offline-gps-capture.md`.

## What was tested automatically

| Suite | Result |
|---|---|
| Go `internal/routeplan` (policy: accept/flag rules, check rules, roles, ids) with `-race` | pass |
| Go `field_routes` migration lint (0001, 0002) | pass |
| App: GPS reading rules (stale fix dropped, median of best readings, spread, accuracy bands, Uganda bounds) | 6 tests pass |
| App: sync queue (oldest first, answer written down, lost connection waits with backoff, expired sign-in kept, refusal stops, conflict marked, crash mid-send resent under the same id, another account's captures never sent, concurrent syncs joined) | 8 tests pass |
| App whole suite | 216 pass |
| Web whole suite, types, lint | 188 pass, clean |

## API checks against the test database

| Case | Expected | Seen |
|---|---|---|
| CCEO first location, GPS 9 m | accepted at once, version 1 | accepted, v1 |
| Same capture id sent again | first answer, nothing filed twice | accepted, v1, one row |
| Same capture id from another person | refused | refused |
| First location at 35 m | waits for review (`accuracy_fair`) | pending |
| Correction sent against the old version | waits, `correction` + `version_conflict` | pending, both flags |
| "Location is correct" | noted, moves nothing | noted |
| Entrance point | waits for review (`entrance`) | pending; approved → entrance v1; road routes use it |
| School not in the sender's reach | refused | not_found |
| Country Director sends a GPS capture | refused (not a capture role) | permission_denied |
| Malformed capture id | refused | invalid_argument |
| PL approves the late correction | version 2, history keeps v1 | v2; change feed lists v1 then v2 |
| Existing `school` / `school_geo_point` rows | never written | unchanged after every case |

## Concurrency (data integrity)

Ten first captures of one school without a location, sent at the same moment by two accounts (5 each):

- exactly **1 accepted** (version 1), **9 held for review** flagged `correction`, `version_conflict`, `competing` (and `large_move` where far apart);
- exactly **one** `location_change` row for version 1; `school_location` at version 1.

The per-school advisory lock serializes them; no lost or doubled write.

## Timings (local gateway, warm, 3 runs each)

| Call | Seconds |
|---|---|
| Offline pack, CCEO (700 schools + 4 planned visits; 190 KB JSON, 18 KB gzip) | 0.44 (first), 0.16, 0.12 |
| Submit a capture | 0.04, 0.03, 0.08 |
| Change feed | 0.02, 0.02, 0.01 |

Not measured: a real mobile network in the field.

## Device tests

(Filled in below as they are run.)
