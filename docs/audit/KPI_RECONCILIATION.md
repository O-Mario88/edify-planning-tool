# KPI Reconciliation & Canonical Metric Registry

**Audit Date:** 2026-11-22  
**Verification Method:** Every metric was independently queried directly against PostgreSQL (`edify_gorn_test`) and reconciled against live Go API responses (`GET /api/v1/country-map/data`, `GetSchoolDirectory`, `GetPage`) and Python `edify_analytics` outputs.

---

## 1. Canonical Metric Reconciliation Table (Live Evidence)

| Metric | Scope / FY | Authoritative SQL Formula | Independent SQL Value | Go API / UI Value | Python Analytics Value | Variance | Status |
|---|---|---|---:|---:|---:|---:|---|
| Operating Schools | Uganda (All) | `count(*) FROM school WHERE deleted_at IS NULL AND operational_status IN ('active','reopened')` | `700` | `700` | `700` | `0` | **Reconciled** |
| Client Schools | Uganda (All) | `... AND lower(school_type) = 'client'` | `558` | `558` | `558` | `0` | **Reconciled** |
| Core Schools | Uganda (All) | `... AND lower(school_type) = 'core'` | `103` | `103` | `103` | `0` | **Reconciled** |
| Champion Schools | Uganda (All) | `... AND lower(school_type) = 'champion'` | `39` | `39` | `39` | `0` | **Reconciled** |
| Core Trained / Core Graduates | Uganda (All) | `... AND lower(school_type) IN ('core_trained','core_graduate')` | `0 / 0` | `0 / 0` | `0 / 0` | `0` | **Reconciled** |
| Total Enrollment | Uganda (All) | `sum(enrollment)` (700/700 schools with enrollment) | `355,575` | `355,575` | `355,575` | `0` | **Reconciled** |
| Median Enrollment | Uganda (All) | `percentile_cont(0.5) WITHIN GROUP (ORDER BY enrollment)` | `527.5` | — | `527.5` | `0.0` | **Reconciled** |
| Active CCEOs | Uganda | `count(DISTINCT sp.id)` where `u.is_active` and role `CCEO` | `20` | `20` | — | `0` | **Reconciled** |
| Mapped UBOS Districts / Sub-Regions | Uganda | `district WHERE sub_region_id IS NOT NULL` / `sub_region` | `136 / 10` | `136 / 10` | — | `0` | **Reconciled** |
| Geo-Located School Pins (Valid Uganda GPS) | Uganda | Valid lat `[-1.6, 4.3]`, lng `[29.4, 35.1]`, excluding `(0,0)` | `683` | `683` | — | `0` | **Reconciled** |
| Confirmed SSA Assessed Schools (FY 2027) | FY 2027 | `count(DISTINCT school_id)` in `ssa_record` (`fy='2027'`, `confirmed`) | `306` | `306` (`covered_schools`) | `306` | `0` | **Reconciled** |
| Confirmed SSA Coverage % (FY 2027) | FY 2027 | `round(306 * 100.0 / 700)` | `43.7%` (`44%` int) | `44%` | `43.7%` | `0` | **Reconciled** |
| Confirmed SSA Average Score (FY 2027) | FY 2027 | `round(avg(average_score), 2)` | `5.91` | `5.91` | `5.91` | `0.00` | **Reconciled** |
| Confirmed SSA FY 2027 vs FY 2026 Compared / Improved / Declined / Unchanged | FY 2027 vs FY 2026 | `delta > 0.05` improved; `delta < -0.05` declined | `306 / 196 / 103 / 7` | — | `306 / 196 / 103 / 7` | `0` | **Reconciled** |
| SSA Average Delta (FY 2027 vs FY 2026) | FY 2027 vs FY 2026 | `round(avg(s27 - s26), 2)` | `+0.88` | — | `+0.88` | `0.00` | **Reconciled** |
| SSA Status Bands (FY 2027: On Track `≥7.5` / Watch `7.0–7.4` / Critical `<7.0`) | FY 2027 | Confirmed FY27 `ssa_record` | `32 / 35 / 239` | — | `32 / 35 / 239` | `0` | **Reconciled** |
| Confirmed SSA Average Score (FY 2026) | FY 2026 | `round(avg(average_score), 2)` | `4.96` | `4.96` | — | `0.00` | **Reconciled** |
| FY 2026 Sub-Region Coverage | FY 2026 | Schools with FY26 activity OR confirmed FY26 SSA | `700 / 700 (100%)` | `700 / 700 (100%)` | — | `0` | **Reconciled** |
| Unique Schools with Completed Visit (All) | FY 2026 | `count(DISTINCT school_id)` where `activity.status='completed'` | `182` (`26.0%`) | `182` | `182` (`26.0%`) | `0` | **Reconciled** |
| Weekly Advances Requested | All | `sum(amount) FROM advance_request` (`280` rows) | `UGX 5,320,000` | `UGX 5,320,000` | — | `UGX 0` | **Reconciled** |
| Target Achievement Ledger Entries | FY 2026 / FY 2027 | `target_achievement_ledger` | `120` provisional (FY26), `1` reversed (FY27) | Separate from verified | — | `0` | **Reconciled** |

---

## 2. Discrepancies Found & Resolved During Audit

1. **Country Map Coverage & SSA Average (`DEF-005` — Fixed):**
   - *Before:* `countrymap_data.go` left `avg_ssa = 0` and computed `covered_schools` using `cluster_id IS NOT NULL` (`90/700 = 13%`), ignoring 306 confirmed FY 2027 SSA records.
   - *After:* Joins confirmed `ssa_record` for the selected `fy`; FY 2027 now reconciles to `306/700` (`44%`), `avg_ssa = 5.91`, and FY 2026 reconciles to `700/700` (`100%`), `avg_ssa = 4.96`.
2. **Financial-Year Boundary Verification:**
   - Uganda FY convention (`Oct 1 – Sep 30`): `schooldirectory.OperationalFY` and `dashboard.operationalFY` both transition on `time.October` (`Oct 2026 – Sep 2027 = FY 2027`). Confirmed identical across Go backend and web UI.
3. **Provisional vs Verified Achievement Separation:**
   - `target_achievement_ledger` maintains distinct `validation_status` values (`provisional`, `verified`, `reversed`); `120` FY26 provisional entries are not counted as verified achievements.
