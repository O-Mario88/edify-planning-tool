-- Native Go Messaging writes: read-thread (auto mark-read), reply, compose,
-- star, and archive (Step 3C — removes Django handoff from /messages).
--
-- Keeps edify_gateway read-only by default; all writes pass through narrow
-- SECURITY DEFINER functions owned by edify_messaging_owner (NOLOGIN NOINHERIT).
-- Preserves read-only system threads and participant-only access enforcement.
--
-- Idempotent. Applied by apply-roles.sh and integration TestMain.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_messaging_owner') THEN
    CREATE ROLE edify_messaging_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_messaging_owner;
GRANT USAGE ON SCHEMA public TO edify_messaging_owner;

GRANT SELECT, INSERT, UPDATE ON messaging_messagethread TO edify_messaging_owner;
GRANT SELECT, INSERT, UPDATE ON messaging_messageparticipant TO edify_messaging_owner;
GRANT SELECT, INSERT, UPDATE ON message TO edify_messaging_owner;
GRANT SELECT (id, name, email, active_role, is_active, deleted_at) ON "user" TO edify_messaging_owner;

CREATE SCHEMA IF NOT EXISTS gateway_messaging AUTHORIZATION edify_messaging_owner;
REVOKE ALL ON SCHEMA gateway_messaging FROM PUBLIC;

SET ROLE edify_messaging_owner;

-- Verifies participant access and marks the thread read for p_user_id.
CREATE OR REPLACE FUNCTION gateway_messaging.mark_thread_read(
  p_thread_id text,
  p_user_id   text,
  p_at        timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  UPDATE public.messaging_messageparticipant
     SET last_read_at = p_at,
         updated_at   = p_at
   WHERE thread_id = p_thread_id AND user_id = p_user_id;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  UPDATE public.message
     SET status     = 'read',
         updated_at = p_at
   WHERE thread_id = p_thread_id AND recipient_id = p_user_id AND status = 'unread';
  RETURN true;
END
$fn$;

-- Sends a reply into an existing thread if caller is a participant and the
-- thread is NOT system-generated. Returns message_id and other participant IDs.
CREATE OR REPLACE FUNCTION gateway_messaging.send_reply(
  p_thread_id text,
  p_sender_id text,
  p_body      text,
  p_at        timestamptz
) RETURNS TABLE(message_id text, recipient_ids text[], subject text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_thread  record;
  v_msg_id  text;
  v_recs    text[];
  v_first   text;
BEGIN
  IF trim(COALESCE(p_body, '')) = '' THEN
    RAISE EXCEPTION 'Message body cannot be empty.';
  END IF;

  SELECT t.id, t.subject, t.is_system_generated, t.category, t.context_type, t.context_id, t.priority
    INTO v_thread
    FROM public.messaging_messagethread t
   WHERE t.id = p_thread_id
     FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Conversation not found.';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.messaging_messageparticipant mp
     WHERE mp.thread_id = p_thread_id AND mp.user_id = p_sender_id
  ) THEN
    RAISE EXCEPTION 'FORBIDDEN: You are not a participant in this conversation.';
  END IF;

  IF v_thread.is_system_generated THEN
    RAISE EXCEPTION 'READONLY: System notifications cannot be replied to.';
  END IF;

  SELECT COALESCE(array_agg(mp.user_id::text ORDER BY mp.user_id), ARRAY[]::text[])
    INTO v_recs
    FROM public.messaging_messageparticipant mp
   WHERE mp.thread_id = p_thread_id AND mp.user_id <> p_sender_id;

  v_first := CASE WHEN array_length(v_recs, 1) >= 1 THEN v_recs[1] ELSE NULL END;
  v_msg_id := 'msg_' || substr(md5(p_thread_id || ':' || p_sender_id || ':' || clock_timestamp()::text), 1, 22);

  INSERT INTO public.message (
    created_at, updated_at, id, sender_id, recipient_id, body,
    category, context_type, context_id, target_route,
    priority, action_required, status, thread_id, is_system_generated
  ) VALUES (
    p_at, p_at, v_msg_id, p_sender_id, v_first, trim(p_body),
    v_thread.category, v_thread.context_type, v_thread.context_id, '/messages?thread=' || p_thread_id,
    COALESCE(v_thread.priority, 'normal'), false, 'unread', p_thread_id, false
  );

  UPDATE public.messaging_messagethread
     SET last_reply_at = p_at,
         updated_at    = p_at
   WHERE id = p_thread_id;

  -- Sender has read their own reply; unarchive recipients so the reply surfaces in Inbox.
  UPDATE public.messaging_messageparticipant
     SET last_read_at = p_at,
         archived_at  = NULL,
         updated_at   = p_at
   WHERE thread_id = p_thread_id AND user_id = p_sender_id;

  UPDATE public.messaging_messageparticipant
     SET archived_at = NULL,
         updated_at  = p_at
   WHERE thread_id = p_thread_id AND user_id <> p_sender_id;

  RETURN QUERY SELECT v_msg_id::text, v_recs, v_thread.subject::text;
END
$fn$;

-- Creates a new conversation thread with the sender and one or more recipients.
CREATE OR REPLACE FUNCTION gateway_messaging.create_thread(
  p_sender_id     text,
  p_recipient_ids text[],
  p_subject       text,
  p_body          text,
  p_priority      text,
  p_context_type  text,
  p_context_id    text,
  p_at            timestamptz
) RETURNS TABLE(thread_id text, message_id text, recipient_ids text[])
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_thread_id text;
  v_msg_id    text;
  v_clean_rec text[];
  v_rec       text;
  v_first     text;
  v_prio      text := COALESCE(NULLIF(lower(trim(p_priority)), ''), 'normal');
BEGIN
  IF trim(COALESCE(p_subject, '')) = '' THEN
    RAISE EXCEPTION 'Subject is required.';
  END IF;
  IF trim(COALESCE(p_body, '')) = '' THEN
    RAISE EXCEPTION 'Message body is required.';
  END IF;
  IF v_prio NOT IN ('normal', 'high', 'urgent', 'low') THEN
    v_prio := 'normal';
  END IF;

  SELECT COALESCE(array_agg(DISTINCT u.id::text ORDER BY u.id::text), ARRAY[]::text[])
    INTO v_clean_rec
    FROM public."user" u
   WHERE u.id = ANY(p_recipient_ids)
     AND u.id <> p_sender_id
     AND u.is_active = true
     AND u.deleted_at IS NULL;

  IF array_length(v_clean_rec, 1) IS NULL THEN
    RAISE EXCEPTION 'Choose at least one active recipient.';
  END IF;

  v_first := v_clean_rec[1];
  v_thread_id := 'thr_' || substr(md5(p_sender_id || ':' || v_first || ':' || clock_timestamp()::text), 1, 22);
  v_msg_id := 'msg_' || substr(md5(v_thread_id || ':' || p_sender_id || ':' || clock_timestamp()::text), 1, 22);

  INSERT INTO public.messaging_messagethread (
    created_at, updated_at, id, subject, context_type, context_id,
    participant_a_id, participant_b_id, category, context_label,
    created_by, is_system_generated, last_reply_at, priority, linked_items
  ) VALUES (
    p_at, p_at, v_thread_id, left(trim(p_subject), 255),
    NULLIF(trim(COALESCE(p_context_type, '')), ''), NULLIF(trim(COALESCE(p_context_id, '')), ''),
    p_sender_id, v_first, 'direct', NULL,
    p_sender_id, false, p_at, v_prio, '[]'::jsonb
  );

  -- Sender participant row (already read).
  INSERT INTO public.messaging_messageparticipant (
    created_at, updated_at, id, user_id, recipient_type, last_read_at, archived_at, starred, thread_id
  ) VALUES (
    p_at, p_at, 'mp_' || substr(md5(v_thread_id || ':' || p_sender_id), 1, 24),
    p_sender_id, 'sender', p_at, NULL, false, v_thread_id
  );

  -- Recipient participant rows (unread).
  FOREACH v_rec IN ARRAY v_clean_rec LOOP
    INSERT INTO public.messaging_messageparticipant (
      created_at, updated_at, id, user_id, recipient_type, last_read_at, archived_at, starred, thread_id
    ) VALUES (
      p_at, p_at, 'mp_' || substr(md5(v_thread_id || ':' || v_rec), 1, 24),
      v_rec, 'to', NULL, NULL, false, v_thread_id
    );
  END LOOP;

  INSERT INTO public.message (
    created_at, updated_at, id, sender_id, recipient_id, body,
    category, context_type, context_id, target_route,
    priority, action_required, status, thread_id, is_system_generated
  ) VALUES (
    p_at, p_at, v_msg_id, p_sender_id, v_first, trim(p_body),
    'direct', NULLIF(trim(COALESCE(p_context_type, '')), ''), NULLIF(trim(COALESCE(p_context_id, '')), ''),
    '/messages?thread=' || v_thread_id,
    v_prio, false, 'unread', v_thread_id, false
  );

  RETURN QUERY SELECT v_thread_id::text, v_msg_id::text, v_clean_rec;
END
$fn$;

-- Updates participant-specific star / archive state strictly for p_user_id.
CREATE OR REPLACE FUNCTION gateway_messaging.update_participant_state(
  p_thread_id text,
  p_user_id   text,
  p_action    text,
  p_at        timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  CASE lower(trim(p_action))
    WHEN 'star' THEN
      UPDATE public.messaging_messageparticipant
         SET starred = true, updated_at = p_at
       WHERE thread_id = p_thread_id AND user_id = p_user_id;
    WHEN 'unstar' THEN
      UPDATE public.messaging_messageparticipant
         SET starred = false, updated_at = p_at
       WHERE thread_id = p_thread_id AND user_id = p_user_id;
    WHEN 'archive' THEN
      UPDATE public.messaging_messageparticipant
         SET archived_at = p_at, updated_at = p_at
       WHERE thread_id = p_thread_id AND user_id = p_user_id;
    WHEN 'unarchive' THEN
      UPDATE public.messaging_messageparticipant
         SET archived_at = NULL, updated_at = p_at
       WHERE thread_id = p_thread_id AND user_id = p_user_id;
    ELSE
      RAISE EXCEPTION 'Unknown message state action: %', p_action;
  END CASE;
  RETURN FOUND;
END
$fn$;

-- Reads messages in a thread strictly if p_user_id is a participant.
CREATE OR REPLACE FUNCTION gateway_messaging.read_thread_messages(
  p_thread_id text,
  p_user_id   text
) RETURNS TABLE(
  id text,
  sender_id text,
  sender_name text,
  body text,
  is_system_generated boolean,
  created_at timestamptz
)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT m.id::text, m.sender_id::text, COALESCE(u.name, m.sender_id)::text,
         m.body::text, m.is_system_generated, m.created_at
    FROM public.message m
    LEFT JOIN public."user" u ON u.id = m.sender_id
   WHERE m.thread_id = p_thread_id
     AND EXISTS (
       SELECT 1 FROM public.messaging_messageparticipant mp
        WHERE mp.thread_id = p_thread_id AND mp.user_id = p_user_id
     )
   ORDER BY m.created_at ASC, m.id ASC;
$fn$;

REVOKE ALL ON FUNCTION gateway_messaging.mark_thread_read(text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_messaging.send_reply(text, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_messaging.create_thread(text, text[], text, text, text, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_messaging.update_participant_state(text, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_messaging.read_thread_messages(text, text) FROM PUBLIC;

RESET ROLE;

GRANT USAGE ON SCHEMA gateway_messaging TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_messaging.mark_thread_read(text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_messaging.send_reply(text, text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_messaging.create_thread(text, text[], text, text, text, text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_messaging.update_participant_state(text, text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_messaging.read_thread_messages(text, text) TO edify_gateway;
