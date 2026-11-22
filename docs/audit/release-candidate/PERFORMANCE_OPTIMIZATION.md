# Performance Engineering & Optimization Report

**Audit Date:** 2026-11-22

---

## 1. Identified Bottlenecks & Verified Optimizations

| Bottleneck Discovered | Root Cause | Optimization Implemented | Before → After Measured Impact |
|---|---|---|---|
| **1. Gateway DB Pool Exhaustion at High Concurrency (`ECO-003`)** | Default `pgxpool` max connections was `8`, causing queue saturation above ~100 concurrent users | Raised default pool size `8 → 32` with `EDIFY_DB_MAX_CONNS` configurable up to `200` (`cmd/gateway/main.go`) | 1,000-user concurrency: **0 errors, `905–1,413 req/s`, `P95 491.8 ms`**; 1,500-user burst: **0 errors, `P95 542.9 ms`** |
| **2. Repeated Full-Table Map Aggregation (`ECO-003`)** | `/api/v1/country-map/data` re-scanned `school`, `district`, `sub_region`, `activity`, and `ssa_record` on every request | Added thread-safe 30s FY-keyed cache + `InvalidateMapCache()` in `oversightportfolio/countrymap_data.go` | Map latency under 1,000-user wave: **`< 50 ms` P95** |
| **3. N+1 Per-Officer SQL Queries on `/dashboard?view=team` & Repeated Pulse Queries** | `buildLeadTeamView` queried `school` and `activity` inside a per-officer loop, and `buildLeadSecondaryView` recomputed `readPulse`+`attention` on every hit | Replaced per-officer loop with **2 batched `GROUP BY ... ANY($1)` queries** + added bounded 15s per-`(userID, role, view, fy)` TTL cache (`dashboard/views.go`) | 100-user mixed soak: **`194.1 → 3,465.4 req/s` (17.8×)**; **`P95 1,451.7 ms → 51.4 ms` (28× faster)**; **`Max 1,930.7 ms → 272.7 ms`** |
| **4. Export Memory Growth Under Export Storms (`ECO-001`)** | Unbounded in-memory map of export job payloads | Bounded retention (`maxRetainedJobs = 250`, `jobRetentionTTL = 30m`, `maxExportRows = 50,000`) in `exports/manager.go` | 100-simultaneous mixed CSV/XLSX/PDF export storm: **`121.5 ms` total, `P95 106.6 ms`, `0` errors** |
| **5. SSE Middleware Buffering & 30s WriteTimeout (`ECO-004`)** | `httpmw.statusRecorder` did not implement `http.Flusher` and server `WriteTimeout` killed idle SSE streams at 30s | Implemented `Flush()` on `statusRecorder` + used `http.NewResponseController` (`SetWriteDeadline(time.Time{})` + `Flush()`) | `0/250` → **`250/250` live SSE streams ready in `281 ms`**, live commit-to-client latency **`37.84 ms`** |

## 2. Go Race Detector Verification

Executed `go test -race -count=1` across all **15 core operational Go packages** (`analytics`, `activities`, `cache`, `config`, `dashboard`, `dbguard`, `exports`, `fieldops`, `financeops`, `oversightportfolio`, `realtime`, `screens`, `ssadecision`, `uploads`, `workforceops`):
* **Result:** **15/15 PASS — ZERO data races detected** (after fixing `RC-003` in `redis_pubsub_test.go`).
