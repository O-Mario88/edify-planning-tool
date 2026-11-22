# Regression Test Coverage & Defect Ledger

**Audit Date:** 2026-11-22

---

## 1. Automated Suite Execution Outcomes

| Layer | Suite | Tests Executed | Outcome |
|---|---|---:|---|
| **Go Backend** | `realtime`, `httpmw`, `exports`, `oversightportfolio`, `coreoversight`, `financeops`, `workforceops`, `fieldops`, `auth`, `schooldirectory`, `myplan`, `clusteroversight`, `myactions`, `escalations`, `personaltimeoff`, `debriefs`, `decisionlog`, `navigation`, `country`, `cache`, `objstore` | `21` packages | **100% PASS** (`go vet` + `go test`) |
| **Python Analytics** | `platform/workers/analytics/tests/` (incl. new `test_reconciliation.py`) | `30 / 30` | **100% PASS** (`0.15s`) |
| **Web Frontend** | `platform/web` (`Vitest` + `tsc --noEmit` + `eslint --max-warnings 0` + `next build`) | `54` files / `358` tests | **100% PASS** (`0` errors, `0` warnings) |
| **Mobile Expo** | `platform/mobile` (`Jest`) | `35` suites / `277` tests | **100% PASS** (`1.59s`) |
| **Live Integration & Browser E2E** | 12 CSV Export round-trips, 250-client SSE fanout, 100-export storm, 50→1,000-user ramp, 25-route desktop + 10 tablet/mobile Playwright sweep, 9 live API security checks | All executed | **PASS** |

---

## 2. Combined Master Defect Register (All 10 Code Defects Remediated)

| Issue ID | Severity | Feature / Handoff | Root Cause | Fix & Regression Test | Status |
|---|---|---|---|---|---|
| **DEF-001** | **P1 High** | Core School Oversight → Sub-Region grouping | `coreoversight/read.go` read `s.sub_region_id` (`NULL` on 700 schools) without district fallback | `COALESCE(s.sub_region_id, d.sub_region_id)` (`go test ./internal/coreoversight/...`) | **Resolved** |
| **DEF-002** | **P1 High** | Finance Weekly & Advance RBAC / SoD | `SubmitWeeklyRequest` & `TransitionAdvance` lacked non-staff external role blocks & action allowlist | Added `isNonStaffFinanceRole` + explicit action allowlist (`financeops/service_test.go` + live `403`) | **Resolved** |
| **DEF-003** | **P1 High** | Workforce Leave & Escalations RBAC | `workforceops` had zero tests and allowed external roles on `RequestLeave` | Hardened RBAC/validation + added `workforceops/service_test.go` + live `403` | **Resolved** |
| **DEF-004** | **P1 High** | Python Analytics statistical integrity | Missing `math.isfinite`/`[0,10]` guards and negative visit-age clamping in `insights.py` | Added `_valid_score`, symmetric zero-score weighting, `max(0, days)` + `test_reconciliation.py` | **Resolved** |
| **DEF-005** | **P2 Medium** | Country Map FY SSA & Coverage reconciliation | `countrymap_data.go` omitted confirmed FY `ssa_record` join (`avg_ssa = 0`) | Joined confirmed `ssa_record` per FY; verified exact match (`5.91`, `306/700 = 44%`) | **Resolved** |
| **DEF-006** | **P2 Medium** | Country Map → Cluster Oversight tab link | Linked `/clusters/oversight/` instead of canonical `/cluster-oversight/` | Fixed in `countryMapData.ts` + regression check in `CountryMapView.test.tsx` | **Resolved** |
| **ECO-001** | **P1 High** | Native Go Exports (truncation, School ID, filters, missing buttons, RAM leak) | Hard `LIMIT 500`, only 4 kinds, no filters, unbounded `m.jobs`, missing buttons on Escalations/PTO/Debrief | Expanded to 11 filtered CSV kinds (`LIMIT 50000`), `edify_school_id` first, bounded 250-job retention, restored buttons, 12/12 round-trips verified | **Resolved** |
| **ECO-002** | **P1 High** | Real-Time Operational Synchronization | No native Go SSE stream when Django offline | Built scoped `internal/realtime/broker.go` + `/api/realtime` + `<RealtimeBridge />` + `broker_test.go` | **Resolved** |
| **ECO-003** | **P1 High** | 1,000-User Concurrency Bottlenecks | Hardcoded `maxDBConnections = 8` + uncached country map query | Configurable `EDIFY_DB_MAX_CONNS` (default 32, max 200) + 30s FY map cache; verified `1,413 req/s` at 1,000 users | **Resolved** |
| **ECO-004** | **P1 High** | SSE Streaming Blocked by Logging Middleware | `httpmw.statusRecorder` lacked `http.Flusher` & server `WriteTimeout` | Used `http.NewResponseController(w)` + added `Flush()` to `statusRecorder`; verified `250/250` live SSE streams | **Resolved** |
