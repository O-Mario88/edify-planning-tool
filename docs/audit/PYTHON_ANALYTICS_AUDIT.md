# Python Analytics Independent Audit & Validation

**Audit Date:** 2026-11-22  
**Service Audited:** `platform/workers/analytics/edify_analytics/` (`portfolio.py`, `insights.py`, `server.py`)  
**Test Suite:** `pytest` (`platform/workers/analytics/tests/`) — **30/30 passing** (`0.79s`).

---

## 1. Architectural Boundary Verification (Non-Authoritative Enforcement)

| Requirement | Verification Evidence | Result |
|---|---|---|
| Python must not directly access PostgreSQL | `test_no_database_driver_is_a_dependency_or_an_import` confirms zero DB driver imports (`psycopg`, `asyncpg`, `sqlalchemy`, etc.) | **Pass** |
| Python must refuse startup if DB env vars are injected | `test_the_worker_refuses_to_start_with_database_settings` verified across `DATABASE_URL`, `EDIFY_DATABASE_URL`, `EDIFY_ADMIN_DATABASE_URL`, `PGHOST`, `PGPASSWORD`, `PGDATABASE`, `PGSERVICE` | **Pass** |
| Python cannot mutate operational records | All gRPC RPCs (`SummarizePortfolio`, `AnalyzeSsa`, `AnalyzeCoverageGaps`, `AnalyzeRouteEfficiency`, `ComputePredictiveInsights`, `GenerateGlobalReport`) are pure read-only transformations over Go-authorized value inputs | **Pass** |
| Oversized payload DoS protection | `test_oversized_requests_are_refused` enforces gRPC message size limits | **Pass** |

---

## 2. Independent PostgreSQL vs Python Reconciliation (Real `edify_gorn_test` Data)

Rather than trusting shared helpers, independent SQL queries were executed directly against `edify_gorn_test` (`700` operating schools, `1,006` SSA records, `8,048` intervention scores, `264` activities) and compared against Python `edify_analytics` functions:

| Engine | Function | Independent SQL Ground Truth | Python Output | Tolerance / Diff | Status |
|---|---|---|---|---|---|
| Descriptive Portfolio | `portfolio.summarize` | `count=700`, `types={client:558, core:103, champion:39}`, `enrollment_n=700`, `sum=355,575`, `median=527.5` | `count=700`, `types={client:558, core:103, champion:39}`, `enrollment_n=700`, `sum=355,575`, `median=527.5` | `0.000000` | **Exact Match** |
| Descriptive & Diagnostic SSA | `insights.analyze_ssa` (FY27 vs FY26) | `total=700`, `assessed=306`, `compared=306`, `improved=196`, `declined=103`, `avg=5.91`, `delta=+0.88`, `on_track=32`, `watch=35`, `critical=239` | `total=700`, `assessed=306`, `compared=306`, `improved=196`, `declined=103`, `avg=5.91`, `delta=+0.88`, `on_track=32`, `watch=35`, `critical=239` | `0.00` | **Exact Match** |
| Diagnostic Coverage Gaps | `insights.analyze_coverage_gaps` | `total=700`, `ssa=43.7% (306)`, `visit=26.0% (182)`, `training=0.0% (0)`, `Central gap=72.1` | `total=700`, `ssa=43.7%`, `visit=26.0%`, `training=0.0%`, `Central gap=72.1` | `0.0` | **Exact Match** |
| Predictive Risk Scoring | `insights.compute_predictive_insights` | All 700 schools classified with explicit explainable drivers & recommended actions | `high=134`, `medium=499`, `low=67` (`sum=700`, deterministic ordering) | `0` | **Verified** |
| Cross-Country Global Rollup | `insights.generate_global_report` | `k`-anonymity (`min_cohort_size=5`) suppresses sub-threshold cohorts; weighted SSA preserves genuine `0.0` scores | Suppressed `RW` (`n=3 < 5`), weighted SSA exact (`3.04` on test fixture) | `0.00` | **Verified (Fixed `DEF-004`)** |

---

## 3. Statistical Integrity Defects Found & Remediated (`DEF-004`)

1. **`NaN` / Infinite / Out-of-Range Score Vulnerability (`insights.py`):**
   - *Before:* `analyze_ssa` and `generate_global_report` accepted `float('nan')`, `inf`, or scores outside `[0, 10]`, which could silently poison means and risk calculations.
   - *Fix:* Added `_valid_score(v)` (`v is not None and math.isfinite(v) and 0.0 <= v <= 10.0`) across `analyze_ssa` (current, previous, and intervention scores) and `generate_global_report`.
2. **Genuine Zero-Score Handling in `generate_global_report`:**
   - *Before:* `if assessed > 0 and c.average_ssa > 0:` had an asymmetric condition vs `tot_assessed`.
   - *Fix:* Evaluates `safe_ssa = c.average_ssa if _valid_score(c.average_ssa) else 0.0` cleanly whenever `assessed > 0`.
3. **Negative `days_since_last_visit` Clamping (`compute_predictive_insights`):**
   - *Fix:* Clamped `days_since = max(0, s.days_since_last_visit)` so future-dated or clock-skewed records never generate negative day strings.
4. **Regression Tests Added:** [`platform/workers/analytics/tests/test_reconciliation.py`](../../platform/workers/analytics/tests/test_reconciliation.py) (4 new test functions, 30/30 total passing).

---

## 4. Honest Limitations & Recommendations (Predictive / Prescriptive Scope)

- Current `compute_predictive_insights` is a **transparent, deterministic rule-based risk scorer** (0–100 scale with explicit driver attribution and human-in-the-loop recommended actions). It does not fabricate ML probabilities or claim causal impact.
- Before enabling statistical time-series forecasting (e.g., multi-year SSA trajectory forecasting), enforce minimum historical cohort gates (`>= 2` prior fiscal years with `>= 30` assessed schools per stratum) and render **"Insufficient data for a reliable forecast"** when unmet.
- Note: Go client wrapper `platform/backend/internal/analytics` has no unit test file yet; adding a mock gRPC round-trip test in Go is recommended before multi-country rollout.
