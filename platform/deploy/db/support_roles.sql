-- Native Go Support Ticket workflow (Step 3A — replaces Django /support redirect).
--
-- Keeps edify_gateway read-only by default; all writes to admin_support_ticket,
-- audit_log, and domain_event_log pass through narrow SECURITY DEFINER functions
-- owned by edify_support_owner (NOLOGIN NOINHERIT).
--
-- Idempotent. Applied by apply-roles.sh and integration TestMain.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_support_owner') THEN
    CREATE ROLE edify_support_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_support_owner;
GRANT USAGE ON SCHEMA public TO edify_support_owner;

GRANT SELECT, INSERT, UPDATE ON admin_support_ticket TO edify_support_owner;
GRANT SELECT (id, name, email, active_role) ON "user" TO edify_support_owner;
GRANT INSERT (
  id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at
) ON domain_event_log TO edify_support_owner;

CREATE SCHEMA IF NOT EXISTS gateway_support AUTHORIZATION edify_support_owner;
REVOKE ALL ON SCHEMA gateway_support FROM PUBLIC;

SET ROLE edify_support_owner;

CREATE OR REPLACE FUNCTION gateway_support.create_ticket(
  p_title         text,
  p_category      text,
  p_description   text,
  p_urgency       text,
  p_reporter_id   text,
  p_reporter_role text,
  p_route         text,
  p_page_title    text,
  p_object_type   text,
  p_object_id     text,
  p_browser       text,
  p_request_id    text,
  p_at            timestamptz
) RETURNS TABLE(ticket_id text, reference text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_id        text;
  v_ref       text;
  v_n         integer;
  v_try       integer;
  v_cat       text := COALESCE(NULLIF(trim(p_category), ''), 'other');
  v_urg       text := COALESCE(NULLIF(trim(p_urgency), ''), 'medium');
BEGIN
  IF trim(COALESCE(p_title, '')) = '' THEN
    RAISE EXCEPTION 'A short summary of the problem is required.';
  END IF;

  SELECT COUNT(*) + 1 INTO v_n FROM public.admin_support_ticket;
  FOR v_try IN 0..100 LOOP
    v_ref := 'TCK-' || lpad((v_n + v_try)::text, 6, '0');
    EXIT WHEN NOT EXISTS (SELECT 1 FROM public.admin_support_ticket t WHERE t.reference = v_ref);
  END LOOP;

  v_id := 'tck_' || substr(md5(v_ref || ':' || p_reporter_id || ':' || clock_timestamp()::text), 1, 22);

  INSERT INTO public.admin_support_ticket (
    created_at, updated_at, id, reference, title, category, description,
    urgency, status, reporter_id, reporter_role, owner_id,
    route, page_title, object_type, object_id, browser, request_id,
    resolution, resolved_at, closed_at
  ) VALUES (
    p_at, p_at, v_id, v_ref, left(trim(p_title), 255), left(v_cat, 32),
    trim(COALESCE(p_description, '')), left(v_urg, 16), 'submitted',
    p_reporter_id, left(COALESCE(p_reporter_role, ''), 64), NULL,
    left(COALESCE(p_route, ''), 255), left(COALESCE(p_page_title, ''), 255),
    left(COALESCE(p_object_type, ''), 64), left(COALESCE(p_object_id, ''), 64),
    left(COALESCE(p_browser, ''), 255), left(COALESCE(p_request_id, ''), 64),
    '', NULL, NULL
  );

  INSERT INTO public.domain_event_log (
    id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at
  ) VALUES (
    'evt_' || substr(md5(v_id || ':' || clock_timestamp()::text), 1, 22),
    'support.ticket.created', 'SupportTicket', v_id, p_reporter_id,
    jsonb_build_object('reference', v_ref, 'category', v_cat, 'urgency', v_urg),
    p_at, p_at
  );

  RETURN QUERY SELECT v_id::text, v_ref::text;
END
$fn$;

CREATE OR REPLACE FUNCTION gateway_support.list_tickets(
  p_caller_id text,
  p_is_admin  boolean,
  p_limit     integer
) RETURNS TABLE(
  id text,
  reference text,
  title text,
  category text,
  description text,
  urgency text,
  status text,
  reporter_id text,
  reporter_role text,
  route text,
  resolution text,
  created_at timestamptz,
  resolved_at timestamptz
)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT t.id::text, t.reference::text, t.title::text, t.category::text,
         t.description::text, t.urgency::text, t.status::text,
         t.reporter_id::text, t.reporter_role::text, t.route::text,
         t.resolution::text, t.created_at, t.resolved_at
    FROM public.admin_support_ticket t
   WHERE p_is_admin OR t.reporter_id = p_caller_id
   ORDER BY t.created_at DESC
   LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 200));
$fn$;

CREATE OR REPLACE FUNCTION gateway_support.transition_ticket(
  p_ticket_id text,
  p_to_status text,
  p_actor_id  text,
  p_note      text,
  p_at        timestamptz
) RETURNS TABLE(ticket_id text, reference text, reporter_id text, from_status text, to_status text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_row record;
BEGIN
  SELECT t.id, t.reference, t.reporter_id, t.status, t.owner_id, t.resolution
    INTO v_row
    FROM public.admin_support_ticket t
   WHERE t.id = p_ticket_id
     FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Support ticket not found.';
  END IF;

  UPDATE public.admin_support_ticket
     SET status      = left(p_to_status, 24),
         owner_id    = COALESCE(owner_id, NULLIF(p_actor_id, '')),
         resolution  = CASE WHEN p_to_status = 'resolved' AND trim(COALESCE(p_note, '')) <> '' THEN trim(p_note) ELSE resolution END,
         resolved_at = CASE WHEN p_to_status = 'resolved' THEN p_at ELSE resolved_at END,
         closed_at   = CASE WHEN p_to_status = 'closed' THEN p_at ELSE closed_at END,
         updated_at  = p_at
   WHERE id = p_ticket_id;

  -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
  RETURN QUERY SELECT v_row.id::text, v_row.reference::text, v_row.reporter_id::text, v_row.status::text, p_to_status::text;
END
$fn$;

REVOKE ALL ON FUNCTION gateway_support.create_ticket(text, text, text, text, text, text, text, text, text, text, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_support.list_tickets(text, boolean, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_support.transition_ticket(text, text, text, text, timestamptz) FROM PUBLIC;

RESET ROLE;

GRANT USAGE ON SCHEMA gateway_support TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_support.create_ticket(text, text, text, text, text, text, text, text, text, text, text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_support.list_tickets(text, boolean, integer) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_support.transition_ticket(text, text, text, text, timestamptz) TO edify_gateway;
