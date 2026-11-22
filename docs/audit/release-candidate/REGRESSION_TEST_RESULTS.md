# Complete Automated Regression Test Results

**Audit Date:** 2026-11-22  
**Branch:** `feature/edify-go-rn-migration`

---

## 1. Automated Test Suite Scorecard

| Layer | Command | Suites / Packages | Tests Passed | Failures | Status |
|---|---|---:|---:|---:|---|
| **Go Backend (Full Tree)** | `cd platform/backend && go test ./internal/...` | **159 packages** | All tests green | **0** | **PASS** |
| **Go Race Detector (Core Operational)** | `cd platform/backend && go test -race -count=1 ./internal/{analytics,activities,cache,config,dashboard,dbguard,exports,fieldops,financeops,oversightportfolio,realtime,screens,ssadecision,uploads,workforceops}/...` | **15 core packages** | All tests green | **0 races** | **PASS** |
| **Go Production-Safety Static Guard** | `go test -v -run TestGatewaySourcesContainNoSchemaChanges ./internal/dbguard/...` | 159 packages scanned | 100% compliant | **0** | **PASS** |
| **Python Analytics Worker** | `cd platform/workers/analytics && .venv/bin/pytest -q` | 3 test modules | **30 / 30** | **0** | **PASS** |
| **Next.js Web Unit & Component Suite** | `cd platform/web && npx vitest run` | **55 test files** | **359 / 359** | **0** | **PASS** |
| **Next.js Web Production Build & TS** | `EDIFY_ENV=development EDIFY_GATEWAY_URL=http://127.0.0.1:8091 npm run build` | **43 App Router routes** | 43 / 43 built | **0** | **PASS** |
| **Web Dependency Security Audit** | `cd platform/web && npm audit --audit-level=moderate` | 424 packages audited | 0 vulnerabilities | **0** | **PASS** |
| **Expo React Native Mobile** | `cd platform/mobile && npx jest` | **35 test suites** | **277 / 277** | **0** | **PASS** |
| **Staging UAT Ecosystem Runner** | `python3 platform/deploy/staging-cutover/uat_journey.py` | 9 end-to-end checks | **9 / 9** | **0** | **PASS** |
| **Read-Only Data Hygiene SQL** | `psql ... -f platform/deploy/staging-cutover/hygiene_check.sql` | 7 SQL checks | **7 / 7** | **0** | **PASS** |

## 2. Requirement Traceability Matrix (Key Critical Invariants)

* **Financial UGX 0 Variance & Non-Staff RBAC:** `internal/financeops/service_test.go`
* **Staff-Only PTO & MFI Escalation Block:** `internal/workforceops/service_test.go`
* **SSA 8-Intervention Decision Intelligence (10 Controlled Scenarios):** `internal/ssadecision/service_test.go`
* **CSV/XLSX/PDF Multi-Format Export Parity & Auth:** `internal/exports/formats_test.go`, `internal/exports/manager_test.go`
* **Bulk Upload Validation, Canonical 8 Interventions & `ReadWrite` Tx:** `internal/uploads/service_test.go` + live HTTP tx check
* **Multi-Replica Redis Pub/Sub SSE Isolation & Replay:** `internal/realtime/broker_test.go`, `internal/realtime/redis_pubsub_test.go`
* **Python Analytics gRPC Client & Trace Propagation:** `internal/analytics/client_test.go` + `platform/workers/analytics/tests/test_reconciliation.py`
* **Production DB Protection & Least-Privilege Writes:** `internal/dbguard/guard_test.go`
