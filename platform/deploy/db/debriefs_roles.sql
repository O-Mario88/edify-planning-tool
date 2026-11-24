-- The Daily Debrief saved through Go, with Django absent
-- (apps.debriefs.field_debrief_service DailyDebriefFlowService._upsert and
-- submit): the day's row, the work it links and who it is routed to.
--
-- The gateway may insert and update those rows (internal/debriefs is their
-- listed writer in dbguard). Unlinking work it no longer names is the one
-- removal, and it is this function's alone: the gateway holds no DELETE.
--
-- Applied by apply-roles.sh and the integration TestMain. Idempotent. New
-- database objects: production needs the owner's approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_debriefs_owner') THEN
    CREATE ROLE edify_debriefs_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_debriefs_owner;
GRANT USAGE ON SCHEMA public TO edify_debriefs_owner;
GRANT SELECT (id, status, kind) ON daily_debrief TO edify_debriefs_owner;
GRANT SELECT (debrief_id, activity_id), DELETE ON daily_debrief_activity_link TO edify_debriefs_owner;

CREATE SCHEMA IF NOT EXISTS gateway_debriefs AUTHORIZATION edify_debriefs_owner;
REVOKE ALL ON SCHEMA gateway_debriefs FROM PUBLIC;

SET ROLE edify_debriefs_owner;

-- _upsert's link sync: a daily debrief still open to edits drops the work its
-- form no longer ticks.
CREATE OR REPLACE FUNCTION gateway_debriefs.unlink_work(p_debrief varchar, p_keep varchar[]) RETURNS void
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  DELETE FROM public.daily_debrief_activity_link l
   USING public.daily_debrief d
   WHERE d.id = l.debrief_id AND d.id = p_debrief AND d.kind = 'daily'
     AND d.status IN ('draft', 'clarification_requested', 'returned')
     AND NOT (l.activity_id = ANY (COALESCE(p_keep, '{}')))
$fn$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_debriefs FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_debriefs TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_debriefs.unlink_work(varchar, varchar[]) TO edify_activities_rw;

GRANT SELECT (id, status, kind, title, submitted_by_role, submitted_by_user_id, date, deleted_at),
      INSERT (id, created_at, updated_at, fy, date, submitted_by_user_id, submitted_by_role, staff_id, partner_id,
              debrief_type, kind, status, title, linked_activity_ids, submitted_at, what_went_well,
              what_did_not_go_well, challenges_faced, recommendations, other_work_description, blockers,
              linked_school_ids, linked_cluster_ids, linked_partner_ids, linked_project_ids, intervention_tags,
              is_restricted_incident, potential_mscs_flag, potential_champion_flag, potential_partner_success_flag,
              recommendation_status, risk_level, source, environment),
      UPDATE (what_went_well, what_did_not_go_well, challenges_faced, recommendations, other_work_description,
              linked_activity_ids, linked_school_ids, status, submitted_at, updated_at)
  ON daily_debrief TO edify_activities_rw;
GRANT SELECT (id, debrief_id, activity_id, school_id, created_at),
      INSERT (id, created_at, updated_at, debrief_id, activity_id, school_id)
  ON daily_debrief_activity_link TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, debrief_id, recipient_user_id, recipient_role, routing_reason, action_required)
  ON daily_debrief_recipient TO edify_activities_rw;
