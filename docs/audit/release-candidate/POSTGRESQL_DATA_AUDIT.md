# PostgreSQL Authoritative Data Audit

**Audit Date:** 2026-11-22  
**Isolated Test Database:** `127.0.0.1:5432/edify_gorn_test` (PostgreSQL 16.15)  
**Production Database Mutations:** ZERO

---

## 1. Hardcoded / Fabricated Operational Data Audit

* Scanned `platform/web/src/app/`, `platform/web/src/components/`, `platform/backend/internal/`, and `platform/workers/analytics/` for hardcoded KPI arrays, mock data constants, or static school/financial figures.
* **Result:** **ZERO** hardcoded operational arrays or fabricated KPI values in any runtime page or API handler. Every count, score, financial balance, map pin, and recommendation is queried live from PostgreSQL.

## 2. Read-Only Data Hygiene Audit (`hygiene_check.sql` Executed Live)

Executed `platform/deploy/staging-cutover/hygiene_check.sql` against `edify_gorn_test`:

| Check | Measured Result | Interpretation |
|---|---|---|
| Active operating schools (`deleted_at IS NULL AND operational_status IN ('active','reopened')`) | **700** | Matches School Directory, Country Map (`700`), and CSV/XLSX/PDF exports (`700`) with **0 variance** |
| `DATA-001`: Schools with `school.sub_region_id IS NULL` | `700` null on `school`, **`0` unresolvable** via `COALESCE(s.sub_region_id, d.sub_region_id)` | Go queries use `COALESCE(s.sub_region_id, d.sub_region_id)` (`DEF-001` fixed) |
| `DATA-002`: `ssa_record.average_score` vs `AVG(ssa_score.score)` | `1,006` SSA records, `0` missing child rows, `0` out-of-range (`0..10`), `868` seeded rows diverge `>0.05` | Flagged as mandatory **read-only staging snapshot check** before Uganda production cutover |
| Canonical `ssa_score.intervention` values | Exact **8 interventions** (`christlike_behaviour`, `enrolment`, `exposure_to_word_of_god`, `financial_health`, `government_requirement`, `leadership`, `learning_environment`, `teaching_environment`), `1,006` rows each (`8,048` total) | Bulk Upload Center (`uploads/service.go` + `SsaUploadCenterView.tsx`) aligned to exact 8 codes (`RC-001` fixed) |
| Activity schedule hygiene | `264` active activities, `41` Sunday dates in seed data, `0` FY mismatches | Reconciled cleanly |
| `school_id` uniqueness | `0` active schools missing `school_id`, `0` duplicates | Authoritative `edify_school_id` present in all school exports |
| Financial integrity (`advance_request`) | `280` rows, **`0` negative amounts**, **`UGX 0` variance** | Exact integer minor-unit arithmetic verified |
| Active catalogue items (`activity_catalogue_item`) | `65` active items | Loaded directly into native Go Planning Drawers (`RC-002` fixed) |

## 3. Staging Fixture Coverage Gap (Documented Honestly)

In `edify_gorn_test`, `daily_debrief` (`0`), `leadership_escalation` (`0`), `evidence_record` (`0`), `partner_payment` (`0`), and `school_loans.application` (`0`) have zero seeded rows. Unit and live synthetic write-and-cleanup tests pass; full multi-row UAT on those tables is queued for the sanitized staging snapshot (`platform/deploy/staging-cutover/uat_journey.py`).
