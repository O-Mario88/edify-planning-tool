# Smart Route Planner — measured performance (2026-11-14)

What was measured, how, and what was not. No figure here is estimated unless it says so.

## Setup

- One Mac (Apple silicon, 8 cores, 16 GB), everything local: Go gateway code called directly
  (`internal/routeplan/zz_measure_test.go`, build tag `compare`, not committed), PostgreSQL
  `edify_gorn_test`, OSRM 26.11 on OpenStreetMap's Uganda extract (Geofabrik, 14 Nov 2026) at
  127.0.0.1:5050.
- Test data: 700 schools, 683 with synthetic coordinates inside Mukono district (15 left
  without coordinates, 2 at 0,0 to exercise the "missing" and "invalid" flags); one CCEO day
  (17 Nov 2026) with 4 planned school visits. Real coordinates and real days will differ.
- Each timing is 20 runs; p50 and p95 reported. Times are server time only (no network to
  a phone, no rendering).

## Results

| What | Measured |
|---|---|
| Open a field day, straight lines only (no routing server) | p50 38.3 ms, p95 41.9 ms |
| Open a field day, road distances, nothing cached | p50 81.9 ms, p95 89.8 ms |
| Open the same day again (road results cached for 6 h) | p50 39.4 ms, p95 40.2 ms |
| Routing requests to open a day, nothing cached | 5 |
| Routing requests for 20 opens of the same day | 5 (95 answered from the cache) |
| A planning session: open, Optimise, move one stop, re-open | 8 routing requests, 6 cache hits |
| Distance between two schools (road) | p50 5.8 ms, p95 7.2 ms |
| School pins, whole-country view | p50 13.9 ms; capped at 400 pins (truncated), 48,050 bytes |
| School pins, ~17 km view | p50 12.2 ms; 178 pins, 21,467 bytes |
| Field-day answer size | 31,909 bytes with the road line at full detail (~1,400 points); 11,326 bytes after the line is simplified (points within 5 m of the line dropped) |
| Road matrix size: shortlist vs every school | ~100 cells (5 stops + up to 5 candidates) vs 466,489 (683 × 683) |
| Test day | 5 of 5 stops feasible, 0 conflicts, 5 eligible suggestions |

What the cache and shortlist buy, read from the table (same machine, same data):

- A day opened again costs no routing requests and about half the time of a cold open
  (39.4 ms against 81.9 ms at p50).
- Asking the routing server only about the day's stops and a short list of nearby eligible
  schools keeps a matrix at about 100 cells instead of about 466,000 for every pair of schools.
- The pin endpoint never sends more than 400 schools; a district-sized view sent 178.

## Provider cost

OSRM is self-hosted: there is no per-request fee; its cost is the server it runs on. With
Google Routes, a day as measured would be 5 requests when first opened and 0 when re-opened
within 6 hours; Google's per-request price is not quoted here (it changes; read it from the
billing account before switching).

## Not measured yet

- Times on a phone over a mobile network (the brief's "representative mobile networks"), and
  map drawing speed on a low-end Android phone. The emulator and simulator runs on this Mac
  are not a fair stand-in.
- The web page's JavaScript size (a production build was not made for this report). MapLibre
  is loaded only when the map is shown.
- Behaviour with more than one person at once (the >500 concurrent users target).
- A comparison against the existing app: the existing app has no route planner, so there is no
  "before" figure to compare against; the comparisons above are between this planner with and
  without its cache, view limit and shortlist.

## Changed after measuring

- The road line was sent at full detail (~1,400 points for 65 km). It is now simplified on the
  server (Douglas–Peucker, 5 m), which took the field-day answer from 31,909 to 11,326 bytes;
  re-measured open times were unchanged (p50 82.9 ms cold, 40.6 ms cached).
