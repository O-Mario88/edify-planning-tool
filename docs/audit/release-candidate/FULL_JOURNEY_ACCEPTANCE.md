# Master Full-Journey Acceptance Test Report

**Audit Date:** 2026-11-22  
**Mode:** Live Local Go Gateway (`EDIFY_EXISTING_APP_URL=""`, `EDIFY_STRICT_READS=true`, Django offline) + PostgreSQL 16.15 (`edify_gorn_test`) + Next.js Web + Python Analytics  
**Test Harness:** `scratch/rc_verify.py` + `platform/deploy/staging-cutover/uat_journey.py` + `go test -race`

---

## 1. End-to-End School-to-Verified-Impact Journey Evidence

| Step | Module / Transition | Live Evidence | Result |
|---|---|---|---|
| **Step 1** | School Directory | Queried `Nama Primary School` (`edify_school_id = 1696`, `id = cmw9p7x5l00nucrekhech`) via `SchoolDirectoryScreenService/GetSchoolDirectory` (`q=1696`) from PostgreSQL | **PASS** |
| **Step 2** | School Profile & Cluster Oversight | Verified `GetSchoolProfile` (`200 OK` for authorized role, `404` anti-enumeration for non-owner CCEO) and `/cluster-oversight/` (`200 OK`) | **PASS** |
| **Step 3** | 8-Intervention SSA Decision Intelligence | `GET /api/v1/schools/cmw9p7x5l00nucrekhech/ssa-recommendations?fy=2027` analyzed all **8/8 canonical interventions**, diagnosed weakest `enrolment` (`5.4/10`, `+1.0` vs FY26 `4.4`), recommended catalogue item `"Fees, Enrolment, and Marketing Management"` with all 7 explainability fields; verified unassessed school returns `risk_priority="unassessed"` with zero invented scores | **PASS** |
| **Step 4** | Planning Drawers & Activity Catalogue | `PlanningDrawerService/GetPlanningDrawer` loaded **65 real active `activity_catalogue_item` trainings** (`RC-002` fixed); all 4 kinds (`schedule`, `assign`, `group-training`, `cluster-meeting`) returned `200 OK` | **PASS** |
| **Step 5 & 6** | My Plan & Calendar | Verified `MyPlanScreenService/GetMyPlan` and `/calendar` (`200 OK`); single-ID reschedule/cancel/edit invariants verified in `internal/activities` & `internal/screens` (`go test -race` PASS) | **PASS** |
| **Step 7** | Funding (Weekly Request → Approvals → Disbursements) | Verified `/fund-requests/weekly`, `/fund-approvals`, `/disbursements` (`200 OK`); exact `UGX 0` integer variance, idempotency keys & RBAC verified in `internal/financeops` (`go test -race` PASS) | **PASS** |
| **Step 8 & 9** | Execution, Evidence, PL Review & IA Verification | Verified `/ia/verification/`, `fieldops.RecordUpload`, `fieldops.IADecideActivity`, `plreview`, and live SSA Bulk Upload (`POST /api/v1/uploads/ssa/import` committed `verification_status='pending'` enforcing SoD, then cleaned up) | **PASS** |
| **Step 10** | Targets, Oversight & Country Map | Verified `/my-targets`, `/team-planning-oversight/`, `/core-schools-oversight/`, and `/api/v1/country-map/data?fy=2027` (`700` active schools, `683` pins, `17` missing coords, `0` variance) | **PASS** |
| **Step 11** | Python Analytics Worker | `30/30` pytest reconciliation tests (`0.00` variance vs SQL) + `internal/analytics` gRPC client tests (`-race` PASS) | **PASS** |
| **Step 12** | Multi-Format Exports | Exported and read back `700` schools in CSV (`65,704 B`), XLSX (`39,961 B`), and PDF (`301,055 B`); confirmed `edify_school_id = 1696` present in all formats | **PASS** |
| **Step 13** | Real-Time SSE Synchronization | Connected Program Lead SSE client received `ssa.bulk_uploaded` event **`37.84 ms`** after PostgreSQL commit (vs `≤ 2,000 ms` target) | **PASS** |
| **Step 14** | Cross-Module Reconciliation | PostgreSQL counts, Map totals, Dashboard tables, Exports, and Analytics agree with **0 variance**; synthetic test records deleted leaving `edify_gorn_test` pristine | **PASS** |

## 2. Activity-Type Coverage (Section 7)

Verified across Go unit/integration (`-race` PASS) and live gateway checks: School Visit, Follow-up Visit, SSA Support, Core School Visit/Training, In-School Training Pair, Group Training, Cluster Meeting, Partner-Delivered Handover/Dating/Return, Special Project (`/projects`), Cancellations, Reschedules, and Returns.
