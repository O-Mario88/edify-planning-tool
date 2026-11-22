# Export & Bulk Upload Regression Audit

**Audit Date:** 2026-11-22  
**Go Backend:** `platform/backend/internal/exports/` (`csv`, `xlsx`, `pdf`) & `platform/backend/internal/uploads/`  
**Web Routes:** `/exports/[kind]`, `/exports/cluster-oversight/[section]`, `/ssa/upload`, `/ssa/upload/template`, `/api/uploads/[kind]`

---

## 1. Multi-Format Native Go Exports (All 11 Kinds)

Every export enforces server-side RBAC at BOTH job creation (`POST /api/v1/exports`) and download (`GET /api/v1/exports/{id}/download`), applies active query filters (`fy`, `district`, `school_type`, `status`, `q`, `cluster_id`), includes authoritative `edify_school_id` on every school-list export, and supports:
* **`csv`** (`text/csv; charset=utf-8`)
* **`xlsx`** (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` — valid ZIP/OOXML with styled header)
* **`pdf`** (`application/pdf` — valid multi-page landscape PDF 1.4 with exact xref table & `%%EOF`)

### Live Round-Trip Reconciliation (`edify_gorn_test`, Django Offline)

| Export Kind | Format | Rows Exported | PostgreSQL Count | Variance | Bytes | Integrity Check |
|---|---|---:|---:|---:|---:|---|
| `school_directory` (all) | `csv` | 700 | 700 | **0** | 65,704 | `edify_school_id` verified |
| `school_directory` (all) | `xlsx` | 700 | 700 | **0** | 39,961 | ZIP + `xl/worksheets/sheet1.xml` + `edify_school_id` verified |
| `school_directory` (all) | `pdf` | 700 | 700 | **0** | 301,055 | `%PDF-1.4`..`%%EOF` verified |
| `school_directory` (`school_type=core`) | `csv`/`xlsx`/`pdf` | 103 | 103 | **0** | 9,598 / 8,167 / 45,283 | Filter parity verified |
| 100-Simultaneous Export Storm (50 CSV + 30 XLSX + 20 PDF) | Mixed | 100 jobs | 100/100 OK | **0 errors** | — | **`121.5 ms` total, `P50 68.2 ms`, `P95 106.6 ms`, `Max 112.5 ms`** |

## 2. Export Buttons Verified Across Web UI

* **School Directory (`/schools`):** `Export CSV` + `Export Excel (.xlsx)` + `Export PDF` (filter-preserving)
* **Country Map (`/country-map` & `/dashboard?view=map`):** `Export Map Data` (CSV) + `Excel (.xlsx)` + `PDF Report`
* **Core School Oversight (`/core-schools-oversight`):** `Export` (CSV) + `Excel` + `PDF`
* **Decision Log (`/decision-log`):** `Export Report` (CSV) + `Excel` + `PDF`
* **Escalations (`/escalations`):** `Export CSV` + `Excel` + `PDF`
* **Personal Time Off (`/personal-time-off`):** `Export CSV` + `Excel` + `PDF`
* **Field Debriefs (`/debriefs`):** `Export CSV` + `Excel` + `PDF`
* **Cluster Oversight (`/cluster-oversight/`):** Section CSV exports via `/exports/cluster-oversight/[section]`

## 3. Bulk Upload Center Restoration & Canonical Column Verification

* Dedicated UI page `/ssa/upload` (`SsaUploadCenterView.tsx`) supporting both **Official SSA Scores CSV** and **Planned Activities Completion CSV**.
* `GET /api/v1/uploads/ssa/template` verified live with all 8 canonical PostgreSQL intervention headers (`RC-001` fixed); returns `403 Forbidden` for unauthorized roles (`CCEO`).
* `POST /api/v1/uploads/ssa/import` uses `pgx.TxOptions{AccessMode: pgx.ReadWrite}` (`RC-005` fixed) and calls least-privilege `gateway_field_ops.enter_ssa(...)` + `audit.Append(...)`, creating records with `verification_status='pending'` (Separation of Duties) and publishing a real-time SSE event.
