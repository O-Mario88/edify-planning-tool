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
--                  course on by its dates (pd_request.status, updated_at) and
--                  closes the reminders that ends (notifications.services.
--                  resolve_condition: notification.resolved_at, status,
--                  action_required, updated_at); StaffPDService.
--                  get_or_create_allocation makes the year's allocation (a
--                  new pd_allocation row). No DELETE, and nothing else.
--
-- The gateway role stays read-only by default (default_transaction_read_only,
-- roles.sql): the page opens a read-write transaction on purpose, only while
-- EDIFY_GO_PAGE_WRITES names it.

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

GRANT SELECT (id, source_event_type, context_type, context_id, resolved_at) ON notification TO edify_mypd_rw;
GRANT UPDATE (resolved_at, status, action_required, updated_at) ON notification TO edify_mypd_rw;

GRANT SELECT (id, staff_id, fy) ON pd_allocation TO edify_mypd_rw;
GRANT INSERT (created_at, updated_at, id, staff_id, fy, country, currency, annual_allocation, status, set_by)
  ON pd_allocation TO edify_mypd_rw;
