-- A Most Significant Change Story submitted from My Targets through Go with
-- Django absent (staff_views.mscs_submit_view): exactly the columns the view's
-- create writes. Its ledger mark uses target_ledger_dirty, already granted.
--
-- Applied by apply-roles.sh and the integration TestMain. Idempotent. A new
-- grant: production needs the owner's approval at cutover.

GRANT INSERT (created_at, updated_at, id, user_id, cluster_id, title, narrative, evidence_uri, story_date, status,
              reviewed_by, reviewed_at, return_reason, school_id, country, intervention, outcome_area)
  ON mscs_story TO edify_activities_rw;
