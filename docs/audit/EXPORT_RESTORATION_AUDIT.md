# Export Restoration & Round-Trip Validation Audit

**Audit Date:** 2026-11-22  
**Remediation Implemented:** `ECO-001` — Expanded Go native export engine (`platform/backend/internal/exports/manager.go`), filter-forwarding Next.js export route (`platform/web/src/app/(app)/exports/[kind]/route.ts`), bounded memory retention, and restored Export CSV buttons across web views.

---

## 1. Defects Found & Remediated in Export Ecosystem

1. **Silent 500-Row Truncation Removed:** `school_directory`, `completed_visits`, `ssa_records`, and `finance_weekly` previously hard-capped queries at `LIMIT 500`, silently dropping 200 of 700 schools on School Directory exports. Raised ceiling to `50,000` rows.
2. **Authoritative Edify School ID & Geographic Hierarchy Restored:** Every school-list CSV export now leads with **`edify_school_id`** (`school.school_id`) distinct from internal `record_id`, `activity_id`, and `ssa_id`, and includes `district`, `sub_region` (via `COALESCE(s.sub_region_id, d.sub_region_id)`), `cluster`, and `enrollment`.
3. **Filter Consistency Restored:** `POST /api/v1/exports` and Next.js `/exports/[kind]` now accept and apply `fy`, `district`, `school_type`, `status`, `q`, and `cluster_id` filters. School Directory's header Export link now forwards active page filters (`/exports/school_directory?district=...&school_type=...&q=...`).
4. **Restored Missing Native Go Export Kinds & UI Buttons:**
   - Expanded native Go CSV engine from **4 → 11 export kinds**: `school_directory`, `core_schools`, `clusters`, `cluster_schools`, `completed_visits`, `ssa_records`, `finance_weekly`, `escalations`, `leave_requests`, `debriefs`, `decision_log` (in addition to `clusteroversight` section CSV exports & client-side Country Map CSV export).
   - Restored header **`Export CSV`** buttons on [`EscalationsView.tsx`](../../platform/web/src/components/pages/EscalationsView.tsx), [`PersonalTimeOffView.tsx`](../../platform/web/src/components/pages/PersonalTimeOffView.tsx), and [`FieldDebriefView.tsx`](../../platform/web/src/components/pages/FieldDebriefView.tsx) alongside existing Export buttons on `School Directory`, `Core School Oversight`, `Decision Log`, `Cluster Oversight`, and `Country Map`.
5. **Memory-Leak Protection Under Export Storms:** Added bounded job retention (`maxRetainedJobs = 250`, `30m` TTL eviction) in `exports.Manager`.

---

## 2. Live Round-Trip Verification Results (Generated → Downloaded → Parsed → Reconciled)

| Export Kind | Applied Filters | Required ID Column | Parsed CSV Rows | DB Ground Truth | SHA-256 Prefix | Status |
|---|---|---|---:|---:|---|---|
| `school_directory` | None | `edify_school_id` | `700` | `700` | `d2d7dd8b2799` | **Exact Match** |
| `school_directory` | `school_type=core` | `edify_school_id` | `103` | `103` | `d5e43a05473d` | **Exact Match** |
| `core_schools` | `fy=2027` | `edify_school_id` | `142` | `142` (`103` Core + `39` Champion) | `e89ff02b1ad0` | **Exact Match** |
| `clusters` | None | `cluster_id` | `15` | `15` | `dcddcf2460db` | **Exact Match** |
| `cluster_schools` | None | `edify_school_id` | `90` | `90` | `870c6bf80f37` | **Exact Match** |
| `completed_visits` | `fy=2026` | `edify_school_id` | `220` | `220` (school-linked visits; 40 cluster-level excluded by school scope) | `c1c7f013c4f7` | **Exact Match** |
| `ssa_records` | `fy=2027` | `edify_school_id` | `306` | `306` | `0926ab0b2996` | **Exact Match** |
| `finance_weekly` | None | `advance_id` | `280` | `280` | `cef991f5d590` | **Exact Match** |
| `escalations` | None | `escalation_id` | `0` | `0` | `9ebacb87fea3` | **Exact Match** |
| `leave_requests` | None | `leave_id` | `0` | `0` | `c0f6a6c8dcd3` | **Exact Match** |
| `debriefs` | None | `debrief_id` | `0` | `0` | `8667cee9867f` | **Exact Match** |
| `decision_log` | None | `decision_id` | `17,662` | `17,662` (`audit_log`) | `25261a9a6423` | **Exact Match** |

---

## 3. Export Storm Concurrency Verification (Scenario F)

- **100 simultaneous export create + download requests** across `school_directory`, `core_schools`, `clusters`, `ssa_records`, and `finance_weekly`:
  - **Errors:** `0 / 100`
  - **Total Elapsed Time:** `251 ms`
  - **P50:** `181.3 ms` | **P95:** `244.9 ms` | **Max:** `250.1 ms`
- **RBAC Enforcement:** Unit + live tests confirm `PartnerFieldOfficer` is refused (`403`) on all 11 staff exports, `CCEO` is refused (`403`) on `finance_weekly`, unrelated users cannot download another user's job ID (`403`), and cross-country principals cannot download another country's export (`403`).
- **Format Note:** Native Go exports currently stream UTF-8 CSV with SHA-256 integrity headers (`X-Content-SHA256`). Native XLSX/PDF rendering and Bulk Upload round-trip templates are noted as Phase-2 staging backlog items in `PRODUCTION_READINESS.md`.
