-- My Professional Development, a page whose read writes (owner, 2026-11-16:
-- "Same writes"; docs/migration/68 §68.7). Applied by apply-roles.sh to a
-- development, test or staging database; never to production without the
-- owner's approval at cutover.
--
-- Roles and grants only. Nothing here creates, alters or drops a table,
-- column, index or constraint, and no row is read or written.
--
--   edify_mypd_rw  NOLOGIN, granted to edify_gateway. Exactly what the
--                  existing page's read writes
--                  (pd_views.my_professional_development_view):
--                  PDCourseTrackingService.sync_dates moves a reader's
--                  course on by its dates (pd_request.status, updated_at);
--                  StaffPDService.get_or_create_allocation makes the year's
--                  allocation (a new pd_allocation row). No DELETE, and
--                  nothing else on a table.
--
-- Closing the reminders the clock ends (notifications.services.
-- resolve_condition) is one narrow function, gateway_pd.close_course_reminders:
-- the gateway is never given UPDATE on notification (the integration test
-- "write a notice" holds it to that). The function closes, for one PD course
-- that exists, only its "starts soon" and "in progress" reminders still open
-- (resolved_at, status 'archived', action_required false, updated_at), as
-- resolve_condition does; its owner is a NOLOGIN role nobody is a member of,
-- holding only that UPDATE and the SELECT its filter reads. EXECUTE is
-- granted to edify_mypd_rw only.
--
-- The gateway role stays read-only by default (default_transaction_read_only,
-- roles.sql): the page opens a read-write transaction on purpose, only while
-- EDIFY_GO_PAGE_WRITES names it. Idempotent. New database objects: production
-- needs the owner's approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_mypd_rw') THEN
    CREATE ROLE edify_mypd_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_mypd_rw;
GRANT USAGE ON SCHEMA public TO edify_mypd_rw;
GRANT edify_mypd_rw TO edify_gateway;

GRANT SELECT (id, staff_id, status, start_date, end_date) ON pd_request TO edify_mypd_rw;
GRANT UPDATE (status, updated_at) ON pd_request TO edify_mypd_rw;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_pd_reminders_owner') THEN
    CREATE ROLE edify_pd_reminders_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_pd_reminders_owner;
GRANT USAGE ON SCHEMA public TO edify_pd_reminders_owner;
GRANT SELECT (id) ON pd_request TO edify_pd_reminders_owner;
GRANT SELECT (source_event_type, context_type, context_id, resolved_at) ON notification TO edify_pd_reminders_owner;
GRANT UPDATE (resolved_at, status, action_required, updated_at) ON notification TO edify_pd_reminders_owner;

CREATE SCHEMA IF NOT EXISTS gateway_pd AUTHORIZATION edify_pd_reminders_owner;
REVOKE ALL ON SCHEMA gateway_pd FROM PUBLIC;

SET ROLE edify_pd_reminders_owner;
CREATE OR REPLACE FUNCTION gateway_pd.close_course_reminders(target_course varchar, events varchar[]) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  closed integer;
BEGIN
  -- Only the two reminders the course clock ends, and only for a course.
  IF target_course IS NULL OR events IS NULL
     OR NOT (events <@ ARRAY['pd_course_starting', 'pd_course_in_progress']::varchar[])
     OR NOT EXISTS (SELECT 1 FROM public.pd_request r WHERE r.id = target_course) THEN
    RETURN 0;
  END IF;
  UPDATE public.notification n
     SET resolved_at = now(), status = 'archived', action_required = false, updated_at = now()
   WHERE n.source_event_type = ANY(events)
     AND n.context_type = 'pd_request'
     AND n.context_id = target_course
     AND n.resolved_at IS NULL;
  GET DIAGNOSTICS closed = ROW_COUNT;
  RETURN closed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_pd.close_course_reminders(varchar, varchar[]) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_pd TO edify_mypd_rw;
GRANT EXECUTE ON FUNCTION gateway_pd.close_course_reminders(varchar, varchar[]) TO edify_mypd_rw;

GRANT SELECT (id, staff_id, fy) ON pd_allocation TO edify_mypd_rw;
GRANT INSERT (created_at, updated_at, id, staff_id, fy, country, currency, annual_allocation, status, set_by)
  ON pd_allocation TO edify_mypd_rw;
