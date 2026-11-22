# Automated & Manual Test Coverage Summary

**Audit Date:** 2026-11-22

---

## 1. Automated Test Execution Summary (All Passing)

| Suite | Scope | Executed Command | Result |
|---|---|---|---|
| **Go Backend Unit & Package Tests** | 18 core operational & infrastructure packages (`coreoversight`, `financeops`, `workforceops`, `oversightportfolio`, `fieldops`, `auth`, `schooldirectory`, `myplan`, `clusteroversight`, `myactions`, `escalations`, `personaltimeoff`, `debriefs`, `decisionlog`, `navigation`, `country`, `cache`, `objstore`) | `go vet` + `go test` | **18/18 packages PASS** (including newly added `workforceops/service_test.go` and expanded `financeops/service_test.go`) |
| **Python Analytics Service (`pytest`)** | Portfolio summary, SSA analysis, coverage gaps, route efficiency, predictive risk, k-anonymity global report, DB isolation, wire zero-preservation, `NaN`/edge-case invariants | `pytest -v platform/workers/analytics/` | **30/30 tests PASS** (`0.79s`) |
| **Web Frontend (`Vitest`)** | Components, pages, auth/session cookies, sidebar active winner, School Directory headers, expandable rows, FivePages, CountryMapView | `npx vitest run` | **54/54 files, 358/358 tests PASS** (`3.11s`) |
| **Web Static Analysis & Production Build** | TypeScript strict check, ESLint (`--max-warnings 0`), Next.js 16.4.6 Turbopack production build | `npx tsc --noEmit`, `npx eslint --max-warnings 0`, `npm run build` | **0 errors, 0 warnings** |
| **Mobile Expo (`Jest`)** | Offline capture, routing, calendar, loans, cluster meetings, acting leadership, partner teams, i18n | `npm test -- --watchAll=false` | **35/35 suites, 277/277 tests PASS** (`1.59s`) |
| **Live Browser E2E Sweep (Playwright)** | 25 web routes at desktop (`1440px`), 5 flagship routes at tablet (`768px`) & mobile (`390px`), interactive map controls, RBAC denials | Headless Chromium vs live Go gateway (`:8091`, Django offline) + `next start` (`:3010`) | **PASS** (`0` console errors, `0` page errors, `0px` horizontal overflow across all viewports) |
| **Live Independent Data & API Reconciliation** | Direct PostgreSQL queries vs Go Map API & Python `edify_analytics` across all 700 schools & 1,006 SSA records | `psql` + Node + Python scripts | **100% exact reconciliation** |
| **Live Concurrency Load Test** | 200 concurrent requests across 20 workers on 5 endpoints | Node load harness vs `:8091` | **326.7 req/sec, P50 31.9ms, P95 169.1ms, P99 320.3ms** |

---

## 2. Remaining Automated Test Gaps (Recommended Next)

1. **Go `internal/analytics` client unit tests:** Currently `[no test files]`; add gRPC mock round-trip test for `AnalyzeSsa` / `ComputePredictiveInsights` / `GenerateGlobalReport`.
2. **Live DB integration tests for empty-in-fixture tables:** `evidence_record`, `partner_payment`, `school_loans.application`, `cluster_leadership.leader_assignment`, and `uploadcenter` bulk CSV upload had `0` rows in `edify_gorn_test`; add seeded fixture integration tests in staging before production cutover.
3. **50,000-school / 500-VU staging load test:** Run k6/Go stress test against a 50k-school sanitized staging clone.
