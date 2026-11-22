# Performance Bottlenecks & Optimization Evidence

**Audit Date:** 2026-11-22

---

## 1. Bottlenecks Identified & Remediated During This Audit

| Bottleneck ID | Severity | Location | Measured Issue | Optimization Applied | Verified Impact |
|---|---|---|---|---|---|
| **PERF-001** | **P1 High** | `platform/backend/cmd/gateway/main.go` | `maxDBConnections` was hardcoded to `8` (default) / `64` (cap), serializing DB queries under 500–1,000 concurrent users. | Raised default pool size to `32` (`defaultMaxDBConns = 32`) and configurable `EDIFY_DB_MAX_CONNS` ceiling to `200`. | Gateway sustained **1,413.1 req/sec** at **1,000 simultaneous users** (`P95 581.1 ms`, `0` pool exhaustion errors). |
| **PERF-002** | **P1 High** | `platform/backend/internal/oversightportfolio/countrymap_data.go` | Every `/country-map` or `/dashboard?view=map` load executed 4 aggregate SQL queries (`EXPLAIN ANALYZE`: `9.4ms` exec + `28.4ms` plan = ~`38ms` per call). Under 120–1,000 simultaneous users, repeated identical FY rollups would saturate PostgreSQL. | Added 30-second FY-keyed thread-safe TTL cache (`mapDataCache`) with `InvalidateMapCache()` hook + `Cache-Control: private, max-age=30`. | Warmed map data serves at O(1) memory latency across all 120 PLs in the 1,000-user ramp benchmark. |
| **PERF-003** | **P1 High** | `platform/backend/internal/exports/manager.go` | Export manager stored every CSV `[]byte` payload in `m.jobs` map indefinitely with zero eviction — guaranteed OOM leak under repeated export storms. | Implemented bounded retention (`maxRetainedJobs = 250`, `30m` TTL eviction) tested via `TestExportExpandedKindsAndBoundedRetention`. | 100-export storm completed in `251 ms` (`P95 244.9 ms`, `0` errors) with strictly bounded heap. |
| **PERF-004** | **P1 High** | `platform/backend/internal/realtime/broker.go` + `httpmw/httpmw.go` | Global `http.Server.WriteTimeout = 30s` kills SSE streams, and `httpmw.statusRecorder` did not implement `http.Flusher`. | Cleared write deadline per SSE connection via `http.NewResponseController(w).SetWriteDeadline(time.Time{})`, switched to `rc.Flush()`, and added `Flush()` to `statusRecorder`. | 250 concurrent SSE streams connected and flushed `event: ready` in `281 ms` with `0` drops. |

---

## 2. Database `EXPLAIN ANALYZE` Findings & Next-Stage Recommendations

- **Hot Table Indexing Status:** Audited `pg_indexes` across `school`, `activity`, `ssa_record`, `ssa_score`, `advance_request`, and `notification` — **122 indexes** already exist (including `ssa_record_fy_8271f2_idx`, `uniq_ssa_record_intervention`, and GiST spatial index `field_routes/0006_spatial_index.sql`).
- **Country Map Query Plan (`EXPLAIN ANALYZE`):** `ssa_record` used `Bitmap Index Scan on ssa_record_fy_8271f2_idx` (`1.3ms`); `school` (`700` rows) used `Seq Scan` (`1.6ms`, expected on 700 rows).
- **Recommended Before 50,000-School Staging Scale:**
  1. Add partial composite index on `school (district_id, operational_status) WHERE deleted_at IS NULL` and `school (name) WHERE deleted_at IS NULL` when `school` crosses 10,000 rows so `GetSchoolDirectory` stays `< 150ms` P95 at 50k schools.
  2. Back `mapDataCache` and `realtime.Broker` with Redis (`internal/cache`) when running multiple horizontal Go replicas.
