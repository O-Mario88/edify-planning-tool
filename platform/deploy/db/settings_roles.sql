-- Native Go Settings two-step verification update (Batch 19).
--
-- Keeps edify_gateway free of direct UPDATE on protected account columns
-- (mfa_enabled, mfa_channel) by routing the validated write through one
-- narrow SECURITY DEFINER function owned by edify_settings_owner.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_settings_owner') THEN
    CREATE ROLE edify_settings_owner NOLOGIN NOINHERIT;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS gateway_settings AUTHORIZATION edify_settings_owner;
REVOKE ALL ON SCHEMA gateway_settings FROM PUBLIC;
GRANT USAGE ON SCHEMA gateway_settings TO edify_gateway;

GRANT SELECT (id, email, phone, mfa_enabled, mfa_channel, mfa_secret, deleted_at, active_role, roles)
  ON public."user" TO edify_settings_owner;
GRANT UPDATE (mfa_enabled, mfa_channel, mfa_secret, updated_at)
  ON public."user" TO edify_settings_owner;

CREATE OR REPLACE FUNCTION gateway_settings.update_two_step(
  p_user_id text,
  p_enabled boolean,
  p_channel text,
  p_at timestamptz
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_channel text := lower(btrim(coalesce(p_channel, '')));
BEGIN
  IF v_channel NOT IN ('email', 'sms', 'app') THEN
    RAISE EXCEPTION 'unsupported mfa channel: %', p_channel;
  END IF;

  UPDATE public."user"
     SET mfa_enabled = p_enabled,
         mfa_channel = v_channel,
         updated_at = p_at
   WHERE id = p_user_id
     AND deleted_at IS NULL;

  IF NOT FOUND THEN
    RETURN false;
  END IF;

  RETURN true;
END
$$;

ALTER FUNCTION gateway_settings.update_two_step(text, boolean, text, timestamptz)
  OWNER TO edify_settings_owner;
REVOKE ALL ON FUNCTION gateway_settings.update_two_step(text, boolean, text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gateway_settings.update_two_step(text, boolean, text, timestamptz) TO edify_gateway;

CREATE OR REPLACE FUNCTION gateway_settings.enroll_totp(
  p_user_id text,
  p_secret  text,
  p_at      timestamptz
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
  IF btrim(coalesce(p_secret, '')) = '' THEN
    RAISE EXCEPTION 'totp secret is required';
  END IF;

  UPDATE public."user"
     SET mfa_secret  = p_secret,
         mfa_enabled = true,
         mfa_channel = 'app',
         updated_at  = p_at
   WHERE id = p_user_id
     AND deleted_at IS NULL;

  IF NOT FOUND THEN
    RETURN false;
  END IF;

  RETURN true;
END
$$;

ALTER FUNCTION gateway_settings.enroll_totp(text, text, timestamptz)
  OWNER TO edify_settings_owner;
REVOKE ALL ON FUNCTION gateway_settings.enroll_totp(text, text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gateway_settings.enroll_totp(text, text, timestamptz) TO edify_gateway;
