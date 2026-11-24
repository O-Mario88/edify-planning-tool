-- Activity evidence uploaded through Go, with Django absent
-- (apps.evidence.services.record_upload).
--
-- A file is sent once, to the gateway's staging endpoint, which checks it and
-- keeps it in private storage under a generated name; the row below remembers
-- whose it is. The save that uses it (an accountability, an evidence drawer)
-- takes it once, keeps it as evidence and records it here. The gateway holds
-- no write on evidence_record or on the activity's evidence status (a
-- protected column, dbguard): it may only ask these functions, owned by a
-- NOLOGIN role nobody is a member of.
--
-- gateway_evidence.staged_upload is Go's own table: the existing application
-- never reads it. Applied by apply-roles.sh and the integration TestMain.
-- Idempotent. New database objects: production needs the owner's approval at
-- cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_evidence_upload_owner') THEN
    CREATE ROLE edify_evidence_upload_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_evidence_upload_owner;
GRANT USAGE ON SCHEMA public TO edify_evidence_upload_owner;
GRANT SELECT (id, deleted_at) ON activity TO edify_evidence_upload_owner;
GRANT UPDATE (evidence_status, updated_at) ON activity TO edify_evidence_upload_owner;
GRANT INSERT ON evidence_record TO edify_evidence_upload_owner;

CREATE SCHEMA IF NOT EXISTS gateway_evidence AUTHORIZATION edify_evidence_upload_owner;
REVOKE ALL ON SCHEMA gateway_evidence FROM PUBLIC;

SET ROLE edify_evidence_upload_owner;

CREATE TABLE IF NOT EXISTS gateway_evidence.staged_upload (
  id             varchar(30)  PRIMARY KEY,
  user_id        varchar(30)  NOT NULL,
  stored_name    varchar(128) NOT NULL,
  original_name  varchar(512) NOT NULL,
  mime_type      varchar(128) NOT NULL DEFAULT '',
  file_extension varchar(16)  NOT NULL,
  file_size      integer      NOT NULL,
  created_at     timestamptz  NOT NULL,
  taken_at       timestamptz
);

-- A file checked and kept, waiting for the save that uses it.
CREATE OR REPLACE FUNCTION gateway_evidence.stage(
  p_id varchar, p_user varchar, p_stored varchar, p_original varchar, p_mime varchar, p_ext varchar,
  p_size integer, p_now timestamptz) RETURNS void
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  INSERT INTO gateway_evidence.staged_upload
    (id, user_id, stored_name, original_name, mime_type, file_extension, file_size, created_at)
  VALUES (p_id, p_user, p_stored, left(p_original, 512), left(p_mime, 128), p_ext, p_size, p_now)
$fn$;

-- The person's own staged file, once, within a day of sending it.
CREATE OR REPLACE FUNCTION gateway_evidence.take(p_id varchar, p_user varchar, p_now timestamptz)
  RETURNS TABLE(stored_name varchar, original_name varchar, mime_type varchar, file_extension varchar, file_size integer)
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  UPDATE gateway_evidence.staged_upload s SET taken_at = p_now
   WHERE s.id = p_id AND s.user_id = p_user AND s.taken_at IS NULL AND s.created_at > p_now - interval '1 day'
  RETURNING s.stored_name, s.original_name, s.mime_type, s.file_extension, s.file_size
$fn$;

-- record_upload's EvidenceRecord, and the activity's evidence marked uploaded.
-- An infected file is kept for review, quarantined and rejected, and the
-- activity is left as it was.
CREATE OR REPLACE FUNCTION gateway_evidence.record(
  p_id varchar, p_activity varchar, p_kind varchar, p_uri varchar, p_original varchar, p_mime varchar,
  p_ext varchar, p_size integer, p_by varchar, p_role varchar, p_scan varchar, p_threat varchar,
  p_preview varchar, p_provider varchar, p_now timestamptz) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_infected boolean := p_scan = 'infected';
BEGIN
  PERFORM 1 FROM public.activity a WHERE a.id = p_activity AND a.deleted_at IS NULL;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  INSERT INTO public.evidence_record (
    id, created_at, updated_at, activity_id, kind, uri, original_name, mime_type, file_extension, file_size,
    storage_provider, uploaded_by, uploader_role, status, review_note, scan_status, quarantined,
    preview_status, view_count)
  VALUES (
    p_id, p_now, p_now, p_activity, p_kind, p_uri, p_original, NULLIF(p_mime, ''), p_ext, p_size,
    p_provider, p_by, NULLIF(p_role, ''),
    CASE WHEN v_infected THEN 'rejected' ELSE 'uploaded' END,
    CASE WHEN v_infected THEN left('Automatically quarantined: malware scan flagged ''' || COALESCE(p_threat, '') || '''.', 512) END,
    p_scan, v_infected,
    CASE WHEN v_infected THEN 'not_required' ELSE p_preview END,
    0);
  IF NOT v_infected THEN
    UPDATE public.activity SET evidence_status = 'uploaded', updated_at = p_now WHERE id = p_activity;
  END IF;
  RETURN true;
END
$fn$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_evidence FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_evidence TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION
  gateway_evidence.stage(varchar, varchar, varchar, varchar, varchar, varchar, integer, timestamptz),
  gateway_evidence.take(varchar, varchar, timestamptz),
  gateway_evidence.record(varchar, varchar, varchar, varchar, varchar, varchar, varchar, integer, varchar, varchar,
                          varchar, varchar, varchar, varchar, timestamptz)
TO edify_activities_rw;
