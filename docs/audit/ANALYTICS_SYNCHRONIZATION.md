# Operational-to-Python Analytics Synchronization Report

**Audit Date:** 2026-11-22  
**Authoritative Flow Verified:** PostgreSQL (`edify_gorn_test`) → Go Scoped Projection (`internal/schools`, `internal/analytics`) → Stateless Python gRPC Worker (`platform/workers/analytics/edify_analytics`) → Authorized Dashboards & Rollups.

---

## 1. Synchronization & Isolation Guarantees

1. **Zero Split-Brain Authority:** Python `edify_analytics` imports **zero database drivers** and **physically refuses to start** if any DB environment variable (`DATABASE_URL`, `EDIFY_DATABASE_URL`, `PGHOST`, etc.) is set (verified by `test_server.py`). Go remains the sole transactional & authorization authority.
2. **Independent Source-to-Analytics Reconciliation (0.00 Variance):**
   - **Portfolio Summary (`700` schools):** `school_count=700`, `clients=558`, `core=103`, `champions=39`, `total_enrollment=355,575`, `median=527.5` — exact `0.000000` match with direct PostgreSQL query.
   - **SSA Trajectory (`FY 2027 vs FY 2026`):** `assessed=306`, `compared=306`, `improved=196`, `declined=103`, `unchanged=7`, `avg_score=5.91`, `avg_delta=+0.88`, `on_track=32`, `watch=35`, `critical=239` — exact `0.00` match with direct PostgreSQL query.
   - **Coverage Gaps (`700` schools):** `ssa_coverage=43.7% (306)`, `visit_coverage=26.0% (182)`, `training_coverage=0.0% (0)`, `Central composite_gap=72.1` — exact match.
   - **Global Cross-Country Report:** `k`-anonymity (`min_cohort_size=5`) suppresses sub-threshold cohorts; zero-score preservation and `NaN`/out-of-range resilience hardened (`DEF-004`).
3. **Cache & Freshness Coordination:**
   - Country Map FY cache (`30s` TTL) exposes `InvalidateMapCache()` so operational school/SSA writes immediately flush stale map snapshots.
   - All analytical surfaces label scope & period clearly (`FY 2027`, `Country-wide system data`) and never misrepresent unassessed schools as `0` scores or claim causal impact without methodology.
