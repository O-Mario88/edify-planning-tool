# Data Integrity & Database Audit Report

**Audit Date:** 2026-11-22  
**Target Database:** `edify_gorn_test` (`127.0.0.1:5432`, PostgreSQL 16.15 — verified isolated non-production copy).  
**Production Database Mutations:** **ZERO.**

---

## 1. Schema & Relational Integrity Checks

| Check | Scope | Result | Severity | Notes |
|---|---|---:|---|---|
| Total tables across schemas | 5 schemas (`public`, `school_loans`, `cluster_leadership`, `country_registry`, `field_routes`) | `446` tables | Info | Clean schema separation for Go-owned modules |
| Schools missing `district_id` or `region_id` | 700 live operating schools | `0` | Pass | All 700 mapped to valid districts |
| Duplicate `school.school_id` | 700 live schools | `0` | Pass | Unique identifiers clean |
| Orphan `school.account_owner_id` | 700 live schools | `0` | Pass | Every owner maps to valid `staff_profile`/`user` |
| Orphan `school.cluster_id` (deleted/missing cluster) | 700 live schools | `0` | Pass | All cluster references valid |
| Multi-active `school_cluster_membership` (`ended_at IS NULL`) | All memberships | `0` | Pass | One authoritative active cluster per school enforced |
| Active membership vs `school.cluster_id` mismatch | All memberships | `0` | Pass | 100% consistent |
| Orphan `activity.school_id` | 264 live activities | `0` | Pass | All activity school references valid |
| Orphan `ssa_record.school_id` | 1,006 live SSA records | `0` | Pass | All SSA school references valid |
| Orphan `evidence_record.activity_id` | All evidence rows | `0` | Pass | Clean |
| Orphan or negative `activity_schedule_cost_line` | All cost lines | `0` | Pass | Zero negative or orphaned costs |
| Negative `activity.est_cost_cents` | 264 live activities | `0` | Pass | Clean |
| Out-of-range `ssa_score.score` (`<0` or `>10`) | 8,048 intervention scores | `0` | Pass | Min `1.5`, Max `9.4` across all 8 interventions |
| Negative amounts in `advance_request` | 280 rows (`UGX 5,320,000` requested) | `0` | Pass | Clean |
| Duplicate `advance_request.disburse_reference` | 280 rows | `0` | Pass | Clean |
| Closed/cleared advance unexplained variance | Closed/reconciled rows | `UGX 0` | Pass | Exact reconciliation |
| Multi-country isolation (`country_registry.country`) | `UG`, `KE`, `RW`, `ET` | `UG`: active (`711` school maps, `39` members); `KE/RW/ET`: draft (`0` schools, `0` members) | Pass | Zero cross-country contamination |

---

## 2. Real Data Anomalies Discovered in Non-Production Snapshot (`edify_gorn_test`)

> **Important:** Per audit policy, historical/seeded rows were **not** silently deleted or mutated in place. Code paths were hardened where needed and safe, reversible SQL remediation plans are documented below.

| Anomaly ID | Severity | Table / Column | Measured Count | Root Cause & Impact | Remediation Status |
|---|---|---|---:|---|---|
| **DATA-001** | **P1 High** | `school.sub_region_id` | `700 / 700` NULL | `district.sub_region_id` is populated on all 136 districts, while denormalized `school.sub_region_id` was left `NULL` during seed/import. Caused `coreoversight` sub-region grouping to drop sub-region labels. | **Code Fixed (`DEF-001`):** `coreoversight/read.go` now uses `COALESCE(s.sub_region_id, d.sub_region_id)`. Safe backfill SQL ready if desired: `UPDATE school s SET sub_region_id = d.sub_region_id FROM district d WHERE s.district_id = d.id AND s.sub_region_id IS NULL AND d.sub_region_id IS NOT NULL;` |
| **DATA-002** | **P1 High** | `ssa_record.average_score` vs `AVG(ssa_score.score)` | `733 / 1,006` differ by `> 0.11` (max diff `0.9375`) | Seeded fixture generated `ssa_record.average_score` independently of the 8 `ssa_score` rows instead of deriving it from `AVG(ssa_score.score)`. Any view reading `average_score` vs recomputing from `ssa_score` would diverge by up to `0.94` pts. | **Documented for Data Hygiene:** Before production cutover, verify production `ssa_record.average_score` against `AVG(ssa_score.score)` (read-only query) and ensure Go `EnterSSA` computes `average_score` strictly from submitted intervention scores. |
| **DATA-003** | **P2 Medium** | `activity.fy`, `activity.planned_date`, `activity.actual_delivery_date` | `4` blank `fy`; `41` Sunday `planned_date`; `260` completed rows missing `actual_delivery_date` | Legacy seeded fixture records bypassed Sunday scheduling guard and omitted `fy` on 4 scheduled rows and `actual_delivery_date` on 260 completed rows. | **Documented:** Derive missing `fy` from `planned_date` (`>= Oct 1 → year+1`), and enforce non-Sunday + `fy` population on all Go write paths (`activities.Service`). |
| **DATA-004** | **P2 Medium** | `school.latitude` / `school.longitude` | `2` rows at `(0, 0)` (Null Island); `15` rows `NULL` | Unverified GPS placeholders (`0,0`) or missing coordinates on 17 of 700 schools. | **Handled Safely:** `countrymap_data.go` explicitly excludes `(0, 0)` and out-of-Uganda bounds (`-1.6..4.3`, `29.4..35.1`), plotting `683` verified school pins and never inventing locations. |
| **DATA-005** | **P3 Low** | `school` geographic concentration in test DB | All `700` schools in Mukono (`Central`) | Synthetic test snapshot only seeded schools in Mukono district while seeding all 136 districts & 10 sub-regions. | **Test Coverage Note:** Multi-sub-region distribution tests should seed schools across ≥5 sub-regions in staging before final UAT sign-off. |
