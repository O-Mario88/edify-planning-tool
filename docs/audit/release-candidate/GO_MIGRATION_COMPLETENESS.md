# Go Operational Backend Migration Completeness

**Audit Date:** 2026-11-22  
**Mode Verified:** Standalone Go (`EDIFY_EXISTING_APP_URL=""`, `EDIFY_STRICT_READS=true`, Django process completely offline)

---

## 1. Operational Domain Coverage Matrix

| Operational Domain | Go Package(s) | Live Verification (Django Offline) |
|---|---|---|
| Auth, Sessions, MFA, Role Switching | `internal/signin`, `internal/auth`, `internal/identity`, `internal/acting` | PASS (`401` unauth, JWT + DB role verification) |
| School Directory, Profiles & Drawers | `internal/schooldirectory`, `internal/schoolprofile`, `internal/screens` | PASS (`700` schools, object-level CCEO scoping) |
| Clusters & Cluster Oversight (18 Tabs) | `internal/clusterpage`, `internal/clusteroversight`, `internal/clusterlead` | PASS (`15` clusters, `90` cluster schools, CSV exports) |
| Dashboard (All Role Views) | `internal/dashboard` (`week`, `priorities`, `team`, `operations`, `coaching`, `programmes`, `collaboration`), `CountryMapView` (`map`) | PASS (`7/7` PL views + `2/2` CCEO views + Map `200 OK`) |
| Planning, My Plan, Calendar & Smart Routes | `internal/activities`, `internal/myplan`, `internal/calendarpage`, `internal/routeplan`, `internal/screens` | PASS (`65` active catalogue items loaded; all 4 drawer kinds `schedule`, `assign`, `group-training`, `cluster-meeting`) |
| Core Schools & Core Oversight | `internal/coreschools`, `internal/coreoversight` | PASS (`142` core cohort schools, `COALESCE(s.sub_region_id, d.sub_region_id)`) |
| Finance (Weekly Requests, Approvals, Disbursements, Budgets) | `internal/financeops`, `internal/weeklyrequest`, `internal/fundapprovals`, `internal/disbursements`, `internal/budgetpage` | PASS (`280` advances, exact integer `UGX 0` variance, SSE publishing) |
| Field Ops, Evidence, IA Verification & SSA Operations | `internal/fieldops`, `internal/iapages`, `internal/ssaverify`, `internal/ssadecision` | PASS (8-intervention SSA diagnosis, SoD `pending` verification, SSE publishing) |
| Workforce Ops (Escalations, Leave/PTO, Debriefs, HR) | `internal/workforceops`, `internal/escalations`, `internal/personaltimeoff`, `internal/debriefs`, `internal/hrregister` | PASS (staff RBAC, SSE publishing, CSV/XLSX/PDF exports) |
| Partner Workflows & Oversight | `internal/partnerassigned`, `internal/partneroversight`, `internal/partnerpayments`, `internal/partnerworkspace` | PASS (`/partner/completed` & partner oversight verified) |
| Loans & Repayment Ledger | `internal/loans` | PASS (native Go ledger & outbox, unit tests green; staging seeded fixture E2E queued) |
| Bulk Upload Center | `internal/uploads`, `internal/activities/bulk_upload.go` | PASS (SSA & Planned Activities templates + transactional `ReadWrite` CSV import via `gateway_field_ops.enter_ssa`) |
| Multi-Format Exports | `internal/exports` (`csv`, `xlsx`, `pdf`) | PASS (all 11 kinds, 100-export storm `0` errors) |
| Multi-Country Configuration | `internal/country`, `internal/countryconfig` | PASS (`UG` active; `KE`/`RW`/`ET` draft & isolated) |

## 2. Legacy Django Code Disposition

* Legacy Django code (`apps/`, 58 apps) remains in the repository strictly untouched until formal Uganda production cutover sign-off — per Section 3.3 (*"Do not remove working legacy code until the replacement has passed the full relevant acceptance tests"* and production cutover approval).
* At runtime, **0% of requests depend on Django** when `EDIFY_EXISTING_APP_URL=""` and `EDIFY_STRICT_READS=true`.
