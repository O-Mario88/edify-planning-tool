# Role Security, RBAC & Country Isolation Matrix

**Audit Date:** 2026-11-22  
**Enforcement Layer:** Go Gateway (`internal/auth`, `internal/rbac`, `internal/country`, `internal/dbguard`)

---

## 1. Adversarial & Negative Security Verification (Executed Live)

| Scenario | Test Execution | Expected | Measured Result |
|---|---|---|---|
| Unauthenticated API requests (`/api/v1/country-map/data`, `/api/v1/realtime/stream`, `/api/v1/uploads/ssa/template`) | Live HTTP without JWT | `401 Unauthorized` | **401 on 3/3 (PASS)** |
| Unauthenticated Web access (`/dashboard`) | Real Chromium Playwright | Redirect to `/login` | **Redirected to `/login` (PASS)** |
| CCEO requesting Admin/IA-only SSA bulk upload template (`/api/v1/uploads/ssa/template`) | Live HTTP with CCEO JWT | `403 Forbidden` | **403 Forbidden (PASS)** |
| CCEO opening another CCEO's unowned school via `GetSchoolProfile` | Live ConnectRPC with CCEO JWT | `404 Not Found` (anti-enumeration) | **404 Not Found (PASS)** |
| `PartnerAdmin` requesting staff `/my-plan` or `ProjectCoordinator` requesting `/clusters` under 1,000-user concurrency | Live load test | `403 Forbidden` | **100% blocked under load (PASS)** |
| Non-staff finance submission & unknown advance transition (`DEF-002`) | `internal/financeops` `-race` tests | `ErrForbidden` / `ErrInvalidInput` | **PASS** |
| Non-staff leave request / MFI escalation (`DEF-003`) | `internal/workforceops` `-race` tests | `ErrForbidden` | **PASS** |
| Cross-country SSE isolation (UG event vs KE subscriber across Redis Pub/Sub replicas) | `TestMultiReplicaRedisPubSubFanoutAndIsolation` `-race` | Zero cross-country leakage | **0 leaks (PASS)** |
| Cross-user export download theft (`AuthorizeDownload`) | `internal/exports` `-race` tests | `ErrForbidden` | **PASS** |
| Least-privilege PostgreSQL write boundary | `internal/dbguard` (`TestGatewaySourcesContainNoSchemaChanges`) across all 159 Go packages | Zero unauthorized DDL/DML | **159/159 PASS** |

## 2. Role Access Matrix (11 Live Roles Resolved in `edify_gorn_test`)

Verified active roles: `Admin`, `CountryDirector`, `RegionalVicePresident`, `ImpactAssessment`, `Program Lead`, `CCEO`, `Accountant`, `HumanResources`, `ProjectCoordinator`, `PartnerAdmin`, `PartnerFieldOfficer` (plus `ClusterLeader` & `BusinessTransformation` tested in unit/mobile suites).
* Every role authenticates via signed JWT verified against live DB user & active role membership (`HttpOnly` cookie on web).
* Country isolation enforced via `country.SchoolIn(...)`, `auth.Principal.Country`, and scoped SSE channels (`UG` active; `KE`/`RW`/`ET` draft isolated).
