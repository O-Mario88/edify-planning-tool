# Security & Privacy Audit Report

**Audit Date:** 2026-11-22  
**Scope:** Authentication, session cookies, server-side RBAC, separation of duties, SQL injection safety, XSS/CSRF posture, secrets hygiene, and multi-country tenant isolation.

---

## 1. Security Control Verification

| Control Area | Implementation Inspected | Verification Result | Status |
|---|---|---|---|
| **Session Cookies** | `platform/web/src/lib/session.ts` & `session.test.ts` | Access token (`edify_at`): `httpOnly: true`, `sameSite: 'lax'`, `secure` on HTTPS. Refresh token: `httpOnly: true`, `sameSite: 'strict'`, scoped to `path: '/auth'` | **Pass** |
| **Authentication Enforcement** | `internal/auth`, `server.go` ConnectRPC interceptors, all REST `HandleFunc` handlers | Every ConnectRPC operational service uses `authenticator.Interceptor()`; every REST `/api/v1/*` handler calls `auther.Authenticate(...)` and returns `401` when absent/invalid | **Pass** |
| **Role-Switch Privilege Escalation** | Live test: `CCEO` calling `IdentityService/SwitchRole` & `SwitchActiveRole` with `role: "Admin"` | Refused (`404`/denied); tokens signed with HMAC-SHA256 JWT secret server-side | **Pass** |
| **Separation of Duties (Finance)** | `financeops/service.go` (`checkWeeklyRole`, `TransitionAdvance`, `DecideMonthlyBudget`) | Live test confirmed `ImpactAssessment`, `CCEO`, and `PartnerFieldOfficer` receive `403` on disbursement/unauthorized finance writes (`DEF-002` closed external-role gap on `SubmitWeeklyRequest` & `TransitionAdvance`) | **Pass (Hardened)** |
| **Separation of Duties (Workforce)** | `workforceops/service.go` (`DecideLeave`, `DecideEscalation`, `RequestLeave`, `RaiseEscalation`) | Live test confirmed `CCEO` receives `403` on self-approval of leave/escalations; external roles blocked from staff leave requests (`DEF-003`) | **Pass (Hardened)** |
| **SQL Injection Posture** | Static scan of `platform/backend/internal/` | All user-supplied values bound via PostgreSQL positional parameters (`$1`, `$2`, ...); zero unescaped user string interpolation in SQL | **Pass** |
| **XSS / HTML Sanitization** | Static scan of `dangerouslySetInnerHTML` in `platform/web/src/` | Used exclusively for theme bootstrap script (`layout.tsx`) and SVG icons passed through `safeIcon(svg)` sanitizer | **Pass** |
| **Tamper-Evident Audit Chain** | `internal/audit` (`audit.Append`) | SHA-256 hash-chained audit entries written inside the same Read-Write PostgreSQL transaction on finance, escalation, leave, and team-action mutations | **Pass** |
| **Production DB Protection Guard** | `internal/server` startup check | Gateway logs explicit `database approved by the production-protection guard` (`hosts: ["127.0.0.1"]`, `superuser: false`, `writable_protected_tables: []`) and refuses unapproved production targets | **Pass** |
| **Multi-Country Isolation** | `country_registry.*` & `internal/country/` | Active `UG` records isolated from draft `KE`, `RW`, `ET`; Python `GenerateGlobalReport` enforces k-anonymity (`min_cohort_size`) | **Pass** |
| **Python Analytics DB Isolation** | `platform/workers/analytics/tests/test_server.py` | Worker physically refuses startup if any DB env var is present and imports zero DB drivers | **Pass** |

---

## 2. Security Issues Found & Remediated

- **`DEF-002` (P1 High — Fixed):** `financeops.SubmitWeeklyRequest` and `financeops.TransitionAdvance` previously lacked explicit Go-layer blocks against non-staff external roles (`ClusterLeader`, `PartnerAdmin`, `PartnerFieldOfficer`, `MfiLoanOfficer`, `MfiPartnerAdmin`) and unknown advance action strings. Remediated in `financeops/service.go` with unit tests in `financeops/service_test.go` and verified live (`403`).
- **`DEF-003` (P1 High — Fixed):** `workforceops.RequestLeave` and `RaiseEscalation` previously blocked only `ClusterLeader`, not external partner/MFI roles, and had zero unit tests. Remediated in `workforceops/service.go` with full RBAC/validation coverage in `workforceops/service_test.go`.

## 3. Advisory Security Note (Non-Blocking for Dev, Required Before Prod Cutover)

- **GitHub Dependabot Alert (observed on push):** Remote repository reported `2 moderate` dependency vulnerabilities on the default branch. Run `npm audit` / `go list -m` vulnerability check and upgrade affected transitive packages before production release.
- **CORS & Strict Transport:** Verify production `EDIFY_CORS_ALLOWED_ORIGINS` is locked to the exact production origin and `EDIFY_JWT_SECRET` / `EDIFY_FIELD_ENCRYPTION_KEY` are provisioned via managed secret store.
