# SSA Decision Intelligence Audit & Verification

**Audit Date:** 2026-11-22  
**Implementation:** `platform/backend/internal/ssadecision/service.go` (`GET /api/v1/schools/{id}/ssa-recommendations?fy=...`)  
**Regression Tests:** `platform/backend/internal/ssadecision/service_test.go` (All 10 Section-10 controlled scenarios — `go test -race` PASS)

---

## 1. Canonical 8 SSA Interventions (Aligned to PostgreSQL `ssa_score`)

| # | PostgreSQL `ssa_score.intervention` | Display Label | Verified Rows in `edify_gorn_test` |
|---|---|---|---|
| 1 | `christlike_behaviour` | Christlike Behaviour | 1,006 |
| 2 | `exposure_to_word_of_god` | Exposure to the Word of God | 1,006 |
| 3 | `financial_health` | Financial Health | 1,006 |
| 4 | `leadership` | Leadership | 1,006 |
| 5 | `government_requirement` | Government Requirements | 1,006 |
| 6 | `learning_environment` | Learning Environment | 1,006 |
| 7 | `teaching_environment` | Teacher's Environment | 1,006 |
| 8 | `enrolment` | Enrolment | 1,006 |

## 2. Live PostgreSQL Verification Evidence

* **Assessed School (`Nama Primary School`, `edify_school_id=1696`, FY 2027):**
  * Analyzed all **8/8 confirmed interventions**.
  * Identified weakest intervention: `enrolment` (`5.40/10`, `high` priority, improved `+1.00` from `4.40` in FY 2026, still below `7.0` target).
  * Mapped directly to active PostgreSQL `activity_catalogue_item`: **`"Fees, Enrolment, and Marketing Management"`**.
  * Returned all 7 mandatory explainability fields (`priority_reason`, `verified_evidence`, `recommended_intervention`, `recommended_activity`, `relevance_reason`, `outcome_to_monitor`, `confidence_and_limitations`).
* **Unassessed School (No confirmed FY 2027 SSA):**
  * Returned `risk_priority = "unassessed"`, `current_ssa_average = null` (zero invented scores or trends), and recommended `Schedule Baseline / Current-FY SSA Collection Visit`.

## 3. All 10 Section-10 Controlled Decision Accuracy Tests (`PASS -race`)

1. `1_severe_leadership_weakness` — `< 4.0` classified `critical`, mapped to Leadership catalogue item.
2. `2_severe_financial_health_weakness` — mapped to Financial Health coaching catalogue item.
3. `3_strong_overall_with_one_critical_intervention` — `7.9` average does NOT mask `3.1` Leadership (`risk_priority = critical`).
4. `4_missing_current_fy_ssa` — returns `unassessed`, recommends SSA collection, never fabricates scores.
5. `5_pending_unconfirmed_ssa_excluded` — pending unverified SSA records excluded from confirmed diagnosis and surfaced as verification prompt.
6. `6_recently_completed_training_suppressed` — already-verified training in current FY suppresses duplicate recommendation and notes impact requires subsequent SSA.
7. `7_already_scheduled_support_suppressed` — already-scheduled activity suppresses duplicate recommendation with date & ID.
8. `8_staff_capacity_constraint_suggests_partner` — switches `delivery_suggestion` to `partner` when officer weekly load meets/exceeds capacity.
9. `9_core_package_obligation_surfaced` — incomplete annual Core School support package surfaced alongside SSA recommendations.
10. `10_improving_vs_declining_comparable_ssa` — exact FY-over-FY delta computed (`-0.60` overall; `-2.00` Leadership decline explained explicitly).
