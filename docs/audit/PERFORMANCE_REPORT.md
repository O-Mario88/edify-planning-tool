# Performance, Concurrency & Stability Report

**Audit Date:** 2026-11-22  
**Environment:** Isolated local non-production benchmark — Go Gateway (`127.0.0.1:8091`, single process) + PostgreSQL 16.15 (`edify_gorn_test`, 700 schools, 1,006 SSA records, 264 activities, 280 advances) + Production Next.js 16.4.6 (`127.0.0.1:3010`).

---

## 1. Live Concurrency Benchmark Results

Executed **200 concurrent authenticated requests across 20 simultaneous workers** spanning 5 distinct operational & analytical endpoints:

| Metric | Measured Result | Target SLA | Status |
|---|---:|---:|---|
| Total Requests / Concurrent Workers | `200` / `20` | Representative burst | Executed |
| Total Elapsed Time | `0.61 s` | — | Fast |
| Sustained Throughput | `326.7 req/sec` | — | Strong |
| Overall P50 Latency | `31.9 ms` | `< 300 ms` | **Pass** |
| Overall P95 Latency | `169.1 ms` | `< 1,000 ms` | **Pass** |
| Overall P99 Latency | `320.3 ms` | `< 3,000 ms` | **Pass** |
| Overall Max Latency | `320.9 ms` | Zero 20s freezes | **Pass** |

### Per-Endpoint Latency Breakdown (40 requests each, 20 concurrent workers)

| Endpoint | Role | P50 (ms) | P95 (ms) | Max (ms) | Notes |
|---|---|---:|---:|---:|---|
| `HomeScreenService/GetHome` | `CCEO` | `29.5` | `146.6` | `150.5` | Well below 300ms target |
| `NavigationService/GetNavigation` | `Program Lead` | `8.8` | `74.2` | `76.5` | Sub-10ms median |
| `SchoolDirectoryScreenService/GetSchoolDirectory` | `CountryDirector` | `147.4` | `320.3` | `320.9` | Heaviest read; still `< 350ms` at 20x concurrency |
| `GET /api/v1/country-map/data?fy=2027` | `CountryDirector` | `38.8` | `160.9` | `161.1` | Full 10-sub-region + 136-district + 683-pin query in `38.8ms` P50 |
| `PageScreenService/GetPage` (`/core-schools-oversight`) | `ImpactAssessment` | `9.6` | `72.4` | `72.8` | Note: canonical path requires trailing slash `/core-schools-oversight/` when called directly on `GetPage` |

---

## 2. Scale Readiness Toward 50,000 Schools / 500 Concurrent Users

### Already Implemented Infrastructure Enablers
- **PostgreSQL Spatial Indexing:** GiST index migration (`field_routes/0006_spatial_index.sql`) for geospatial lookups.
- **Redis Cache & Distributed Rate Limiting:** `internal/cache` RESP2/TLS client with graceful in-memory fallback.
- **Object Storage Offloading:** `internal/objstore` AWS SigV4 S3/Spaces/R2 client for evidence & reports.
- **Country Map Pin Capping & Private Cache-Control:** `countrymap_data.go` bounds pins (`LIMIT 1500` prioritized by Core/Champion cohorts) and emits `Cache-Control: private, max-age=30`, while `uganda_districts.geojson` (`178 KB`) is server-cached in memory once per process for instant SSR without tile-server latency.

### Required Before 50,000-School Production Scale
1. **Staging Scale Test (Blocked Locally):** Local `edify_gorn_test` holds `700` schools (`446` tables). Run a synthetic **50,000-school / 500-VU** k6 or Go load test in staging with PgBouncer + Redis enabled before full multi-country rollout.
2. **School Directory P95 Optimization:** `GetSchoolDirectory` (`147.4ms` P50 on 700 schools) should be benchmarked with `EXPLAIN ANALYZE` on 50k rows to confirm composite indexes on `(deleted_at, operational_status, district_id, name)`.
3. **Cache `GET /api/v1/country-map/data` in Redis:** Add a 60s FY-keyed Redis cache in `countrymap_data.go` once school volume exceeds 5,000 rows so repeated map opens across 500 concurrent users hit O(1) memory.
