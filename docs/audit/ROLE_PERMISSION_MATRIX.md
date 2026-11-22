# Role-Based Access Control (RBAC) & Permissions Matrix

**Audit Date:** 2026-11-22  
**Scope:** All 16 canonical system roles verified against `navigation/rules.json`, Go `PageScreenService` gates, REST API role guards, and live multi-role test tokens in `edify_gorn_test`.

---

## 1. Role Inventory & Verified Navigation Coverage

Prior live audit (`9b7291cd8`) + current audit verified **417/417 positive role-page checks passing** and **110/110 negative RBAC page checks refused**, plus REST API separation-of-duties enforcement below:

| Role | Nav URLs | Country Map (`/country-map`) | Dashboard Map (`/dashboard?view=map`) | Weekly Finance Submit | Finance Disburse (`Accountant`) | Leave Approve (`PL/CD/HR`) | Escalation Decide (`PL/CD/RVP`) | Admin Settings / Users |
|---|---:|---|---|---|---|---|---|---|
| **Admin** | 117 | Allowed | Allowed | Allowed | Allowed | Allowed | Allowed | Allowed |
| **CountryDirector (CD)** | 54 | Allowed | Allowed | Allowed | **Denied (`403`)** | Allowed | Allowed | Denied |
| **RegionalVicePresident (RVP)** | 35 | Allowed | Allowed | Allowed | **Denied (`403`)** | Denied (`403`) | Allowed | Denied |
| **RegionalProgramLead (RPL)** | 20 | Allowed | Allowed | Allowed | **Denied (`403`)** | Denied (`403`) | Denied (`403`) | Denied |
| **ImpactAssessment (IA)** | 41 | Allowed | Allowed | Allowed | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied** |
| **Program Lead (PL)** | 40 | Denied (`403` on `/country-map`) | Allowed | Allowed | **Denied (`403`)** | Allowed | Allowed | Denied |
| **CCEO** | 33 | Denied (`403` on `/country-map`) | Allowed | Allowed | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | Denied |
| **Accountant** | 20 | **Denied (`403`)** | **Denied (`403`)** | Allowed | **Allowed** | **Denied (`403`)** | **Denied (`403`)** | Denied |
| **HumanResources (HR)** | 39 | **Denied (`403`)** | **Denied (`403`)** | Allowed | **Denied (`403`)** | **Allowed** | **Denied (`403`)** | Denied |
| **ProjectCoordinator** | 18 | **Denied (`403`)** | **Denied (`403`)** | Allowed | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | Denied |
| **BusinessTransformationOfficer** | 12 | **Denied (`403`)** | **Denied (`403`)** | Allowed | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | Denied |
| **PartnerAdmin** | 14 | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | Denied |
| **PartnerFieldOfficer** | 14 | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | Denied |
| **MfiPartnerAdmin** | 12 | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | Denied |
| **MfiLoanOfficer** | 12 | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | Denied |
| **ClusterLeader** | 0 (App-only) | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | **Denied (`403`)** | Denied |

---

## 2. Live Negative Authorization Tests Executed Against Go Gateway (`127.0.0.1:8091`)

| Test Case | Caller Role | Endpoint | HTTP Status | Expected | Outcome |
|---|---|---|---:|---:|---|
| Unauthenticated map read | None | `GET /api/v1/country-map/data` | `401` | `401` | **Pass** |
| Accountant map read | `Accountant` | `GET /api/v1/country-map/data` | `403` | `403` | **Pass** |
| Partner map read | `PartnerFieldOfficer` | `GET /api/v1/country-map/data` | `403` | `403` | **Pass** |
| Partner weekly finance submit (`DEF-002` fix) | `PartnerFieldOfficer` | `POST /api/v1/ops/weekly-requests` | `403` | `403` | **Pass** |
| IA separation-of-duties disbursement | `ImpactAssessment` | `POST /api/v1/ops/weekly-requests/{id}/transition` (`disburse`) | `403` | `403` | **Pass** |
| CCEO self-approve leave | `CCEO` | `POST /api/v1/ops/leave/{id}/decide` | `403` | `403` | **Pass** |
| CCEO self-resolve escalation | `CCEO` | `POST /api/v1/ops/escalations/{id}/decide` | `403` | `403` | **Pass** |
| CCEO advance disbursement | `CCEO` | `POST /api/v1/ops/advances/{id}/transition` (`disburse`) | `403` | `403` | **Pass** |
| CCEO privilege escalation role switch | `CCEO` | `POST /edify.identity.v1.IdentityService/SwitchRole` (`Admin`) | `404` / refused | Non-2xx | **Pass** |
| Accountant browser access to `/country-map` & `/dashboard?view=map` | `Accountant` | Playwright GET | `0` map components rendered (`NotMovedYet` refusal) | Refused | **Pass** |

---

## 3. Acting Leadership & Multi-Country Isolation Notes

- **Acting Leadership (`internal/acting/`):** Effective start/end dates are enforced server-side when issuing acting notices/tokens (`acting_until`), without mutating substantive roles in `"user".roles`.
- **Multi-Country Isolation (`country_registry.*`):** `UG` (`active`, 711 mapped schools, 39 memberships) is completely isolated from `KE`, `RW`, and `ET` (`draft`, 0 mapped schools, 0 memberships).
- **Anomaly Flagged for Governance (`P3`):** One legacy test account in `edify_gorn_test` carries `active_role = 'Partner'` (`temp-partner-...`), outside the 16 canonical role names; it is cleanly refused by all Go role allowlists (`default deny`).
