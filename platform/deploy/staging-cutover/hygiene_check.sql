-- =============================================================================
-- Edify Planning & Monitoring — Read-Only Staging Snapshot Data Hygiene Audit
-- =============================================================================
-- SAFE: 100% READ-ONLY (SELECT statements only; zero mutations).
-- Run against a sanitized staging clone BEFORE any Uganda production cutover:
--   psql "$STAGING_READONLY_DATABASE_URL" -v ON_ERROR_STOP=1 -f hygiene_check.sql
-- =============================================================================

\echo '=== 1. DATABASE IDENTITY & SAFETY CONFIRMATION ==='
SELECT current_database() AS database_name,
       current_user AS db_user,
       inet_server_addr() AS server_addr,
       now() AT TIME ZONE 'UTC' AS checked_at_utc;

\echo '=== 2. DATA-001: SCHOOLS WITH NULL sub_region_id (FALLBACK VIA district.sub_region_id) ==='
SELECT count(*) AS total_active_schools,
       count(*) FILTER (WHERE s.sub_region_id IS NULL) AS school_sub_region_null,
       count(*) FILTER (WHERE COALESCE(s.sub_region_id, d.sub_region_id) IS NULL) AS unresolvable_sub_region
FROM school s
LEFT JOIN district d ON d.id = s.district_id
WHERE s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened');

\echo '=== 3. DATA-002: ssa_record.average_score VS AVG(ssa_score.score) RECONCILIATION ==='
WITH score_agg AS (
  SELECT ssa_record_id,
         count(*) AS score_rows,
         round(avg(score)::numeric, 2) AS computed_avg,
         min(score) AS min_score,
         max(score) AS max_score
  FROM ssa_score
  GROUP BY ssa_record_id
)
SELECT count(*) AS total_ssa_records,
       count(*) FILTER (WHERE sa.score_rows IS NULL) AS records_without_child_scores,
       count(*) FILTER (WHERE sa.score_rows IS NOT NULL AND abs(COALESCE(r.average_score, 0) - sa.computed_avg) > 0.05) AS avg_score_mismatch_gt_0_05,
       count(*) FILTER (WHERE sa.min_score < 0 OR sa.max_score > 10) AS out_of_range_scores_outside_0_10
FROM ssa_record r
LEFT JOIN score_agg sa ON sa.ssa_record_id = r.id
WHERE r.deleted_at IS NULL;

\echo '=== 4. ACTIVITY SCHEDULE HYGIENE (SUNDAY DATES & FISCAL YEAR ALIGNMENT) ==='
SELECT count(*) AS total_activities,
       count(*) FILTER (WHERE planned_date IS NOT NULL AND extract(dow FROM planned_date) = 0) AS sunday_planned_activities,
       count(*) FILTER (
         WHERE planned_date IS NOT NULL AND fy ~ '^[0-9]{4}$'
           AND fy::int <> (CASE WHEN extract(month FROM planned_date) >= 10 THEN extract(year FROM planned_date)::int + 1 ELSE extract(year FROM planned_date)::int END)
       ) AS fy_date_mismatch_activities
FROM activity
WHERE deleted_at IS NULL;

\echo '=== 5. SCHOOL ID UNIQUENESS & ORPHANED REFERENCES ==='
SELECT count(*) AS active_schools_missing_edify_id
FROM school
WHERE deleted_at IS NULL AND (school_id IS NULL OR btrim(school_id) = '');

SELECT school_id, count(*) AS duplicate_count
FROM school
WHERE deleted_at IS NULL AND school_id IS NOT NULL AND btrim(school_id) <> ''
GROUP BY school_id
HAVING count(*) > 1
LIMIT 20;

\echo '=== 6. FINANCIAL INTEGRITY (NEGATIVE AMOUNTS CHECK) ==='
SELECT count(*) AS total_advances,
       count(*) FILTER (WHERE COALESCE(amount, 0) < 0 OR COALESCE(disbursed_amount, 0) < 0 OR COALESCE(accounted_amount, 0) < 0 OR COALESCE(returned_amount, 0) < 0) AS negative_advance_rows
FROM advance_request;

\echo '=== 7. STAGING E2E FIXTURE COVERAGE CHECK ==='
SELECT 'school' AS entity, count(*) AS rows FROM school WHERE deleted_at IS NULL
UNION ALL SELECT 'cluster', count(*) FROM cluster WHERE deleted_at IS NULL
UNION ALL SELECT 'activity', count(*) FROM activity WHERE deleted_at IS NULL
UNION ALL SELECT 'ssa_record', count(*) FROM ssa_record WHERE deleted_at IS NULL
UNION ALL SELECT 'advance_request', count(*) FROM advance_request
UNION ALL SELECT 'partner', count(*) FROM partner WHERE deleted_at IS NULL
UNION ALL SELECT 'daily_debrief', count(*) FROM daily_debrief WHERE deleted_at IS NULL
UNION ALL SELECT 'leadership_escalation', count(*) FROM leadership_escalation;
