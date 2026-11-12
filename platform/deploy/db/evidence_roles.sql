-- Which forms an activity has in, and nothing else of its evidence. Applied
-- by apply-roles.sh to a development, test or staging database, after
-- decision_log_roles.sql; never to production without the owner's approval
-- at cutover.
--
-- The gateway may not read evidence_record: it holds private storage keys,
-- original file names, uploaders and review notes
-- (TestGatewayRoleCanNeitherWriteNorReadSecrets names it as a table the
-- gateway must not read). A partner's completed work is complete only with
-- its form uploaded and not quarantined (apps.activities.completion_columns:
-- _records and forms_in_q read activity_id and kind, quarantined=False), so
-- this view shows exactly that: each activity's uploaded kinds, one row per
-- kind.
--
-- Nothing here touches a table, column, index, constraint or row of the
-- existing schema. The view lives in gateway_read, owned by
-- edify_audit_view_owner (decision_log_roles.sql): the NOLOGIN owner of the
-- gateway's narrow views, which no one is a member of. It is granted the
-- three evidence columns the view reads and nothing else of the table.
-- TestTheEvidenceViewShowsOnlyUploadedKinds checks it.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_audit_view_owner') THEN
    CREATE ROLE edify_audit_view_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO edify_audit_view_owner;
GRANT SELECT (activity_id, kind, quarantined) ON evidence_record TO edify_audit_view_owner;

CREATE SCHEMA IF NOT EXISTS gateway_read AUTHORIZATION edify_audit_view_owner;
REVOKE ALL ON SCHEMA gateway_read FROM PUBLIC;

-- Built as the owner, so the view reads with the owner's privileges only.
SET ROLE edify_audit_view_owner;
CREATE OR REPLACE VIEW gateway_read.activity_evidence_kind AS
SELECT DISTINCT e.activity_id, e.kind
FROM public.evidence_record e
WHERE e.quarantined = false;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_read TO edify_gateway_ro;
GRANT SELECT ON gateway_read.activity_evidence_kind TO edify_gateway_ro;
