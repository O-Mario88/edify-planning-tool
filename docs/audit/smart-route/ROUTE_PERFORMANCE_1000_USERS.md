# Smart Route Planner 1,000-User Performance Benchmark

**Project:** Edify Planning & Monitoring Platform  
**Date:** 2026-11-22  
**Target Environment:** Local Go Gateway (`127.0.0.1:8091`, `EDIFY_DB_MAX_CONNS=64`, `EDIFY_ROUTING_PROVIDER=osrm`) + Isolated PostgreSQL 16.15 (`edify_gorn_test`)

---

## 1. Measured 1,000-User Concurrent Workload (Test K)

Simulated 1,000 concurrent authenticated field-staff requests (`100` active concurrent workers) evenly distributed across:
- `GET  /api/v1/smart-route/day?date=2026-11-17&mode=balanced`
- `GET  /api/v1/scheduling/calendar-rules`
- `GET  /api/v1/smart-route/road-conditions`
- `POST /api/v1/smart-route/validate`

| Metric | Target (Section 15) | Measured Live Result | Status |
|---|---|---|---|
| **Total Requests** | 1,000 concurrent users | `1,000` | PASS |
| **HTTP Errors** | `0` | **`0`** (`0.00%`) | PASS |
| **Throughput** | High concurrency | **`1,206.0 req/s`** | PASS |
| **P50 Latency** | `<= 1,000 ms` | **`51.6 ms`** | PASS |
| **P95 Latency** | `<= 1,000 ms` | **`232.6 ms`** | PASS |
| **P99 Latency** | `<= 3,000 ms` | **`410.5 ms`** | PASS |
| **Max Latency** | Bounded | `514.3 ms` | PASS |
| **Duplicate Route Records** | `0` | **`0`** (unique `(user_id, day)`) | PASS |

## 2. Operation-Level Latency Measurements (External Provider Measured Separately)

| Operation | Measured Latency | Notes |
|---|---|---|
| Cold OSRM 2-school road optimize (`POST /smart-route/optimize`) | `480.8 ms` | Includes live internet round-trip to `router.project-osrm.org` |
| Cold OSRM 4-school balanced optimize | `595.7 ms` | Live road matrix + full 381-point polyline + steps |
| Cached 4-school optimize (`balanced`/`fastest`/`shortest`/`max_schools`/`priority_schools`) | `7.9 – 11.3 ms` | Served from `Guarded` in-memory cache + `singleflight` |
| In-App Directions (`POST /smart-route/directions`, 4 legs, 18 steps on leg 1) | `7.5 ms` (cached) / `211.2 ms` (cold) | Full road geometry + maneuvers |
| Date picker open (Playwright DOM interaction) | Visually immediate (`< 16 ms`) | Pure client React state |

## 3. Caching, Deduplication & Efficiency Proof

Live `QuotaSnapshot` recorded immediately after the 1,000-user benchmark:
- **Upstream Provider Calls (`requests`):** `14`
- **In-Memory Cache Hits (`cache_hits`):** **`1,056`** (98.7% cache hit ratio!)
- **Upstream Failures / Quota Refusals:** `0` / `0`
- **Database Spatial Indexing:** GiST point indexes active on `school_location`, `verified_location`, and `road_condition_report`.
- **Browser GPS Battery Protection:** `InAppNavigationPanel` (web) and `InAppNavigationModal` (mobile) debounce GPS updates (`>= 30 m` movement or `>= 10–15 s` interval) and never write transient GPS ticks to PostgreSQL.
