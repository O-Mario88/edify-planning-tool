-- Signing in, owned by the Go gateway (owner brief, 2026-11-11: "All
-- authentication and user workflows must be handled by Go"). Applied by
-- apply-roles.sh to a development, test or staging database; never to
-- production.
--
-- Roles and grants only. Nothing here creates, alters or drops a table,
-- column, index or constraint, and no row is read or written.
--
--   edify_identity_rw  NOLOGIN, granted to edify_gateway. Exactly the columns
--                      the existing sign-in reads and writes
--                      (apps/accounts/auth_services.py, lockout_service.py,
--                      mfa_service.py), and nothing else: no DELETE anywhere,
--                      no UPDATE of any audit row, and on "user" only the
--                      password, lockout, reset and activation columns.
--
-- The gateway role stays read-only by default (default_transaction_read_only,
-- roles.sql): a sign-in write opens a read-write transaction on purpose.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_identity_rw') THEN
    CREATE ROLE edify_identity_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

-- Start from nothing, so re-running after a query changes never leaves a
-- grant behind that the code no longer needs.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_identity_rw;
GRANT USAGE ON SCHEMA public TO edify_identity_rw;
GRANT edify_identity_rw TO edify_gateway;

-- The account: who signs in, their password, lockout and second factor.
GRANT SELECT (
  id, email, name, phone, password, roles, active_role, status, is_active, deleted_at,
  mfa_enabled, mfa_channel, mfa_secret,
  failed_login_count, failed_login_streak_started_at, locked_until, last_lockout_at,
  lockout_cycle_count, lockout_escalated,
  password_reset_token_hash, password_reset_expires
) ON "user" TO edify_identity_rw;
GRANT UPDATE (
  failed_login_count, failed_login_streak_started_at, locked_until, last_lockout_at,
  lockout_cycle_count, lockout_escalated, last_login_at,
  password, password_set_at, password_reset_token_hash, password_reset_expires,
  status, is_active
) ON "user" TO edify_identity_rw;

-- Accepting an invitation activates the staff profile, unless an open
-- onboarding plan still gates it.
GRANT SELECT (id, user_id, deleted_at, onboarding_state) ON staff_profile TO edify_identity_rw;
GRANT UPDATE (onboarding_state, updated_at) ON staff_profile TO edify_identity_rw;
GRANT SELECT (staff_id, status) ON hr_onboarding_plan TO edify_identity_rw;

-- Sessions: rotating refresh tokens, stored as hashes.
GRANT SELECT (id, user_id, token_hash, family_id, expires_at, revoked_at) ON refresh_token TO edify_identity_rw;
GRANT INSERT (id, user_id, token_hash, family_id, parent_id, expires_at, created_at, updated_at)
  ON refresh_token TO edify_identity_rw;
GRANT UPDATE (revoked_at, consumed_at, reuse_detected_at) ON refresh_token TO edify_identity_rw;

-- The second factor's codes, stored as hashes.
GRANT SELECT (id, user_id, channel, code_hash, client_token_hash, expires_at, consumed_at, attempts, created_at)
  ON mfa_challenge TO edify_identity_rw;
GRANT INSERT (id, user_id, channel, destination_hint, code_hash, client_token_hash, expires_at,
              attempts, deliveries, last_sent_at, created_at, updated_at)
  ON mfa_challenge TO edify_identity_rw;
GRANT UPDATE (expires_at, consumed_at, attempts, updated_at) ON mfa_challenge TO edify_identity_rw;

-- Invitations: read, and spent once.
GRANT SELECT (id, user_id, token_hash, expires_at, accepted_at, revoked_at) ON user_invitation TO edify_identity_rw;
GRANT UPDATE (accepted_at) ON user_invitation TO edify_identity_rw;

-- The audit chain: the tail is read and rows are added; nothing is updated.
GRANT SELECT (seq, hash) ON audit_log TO edify_identity_rw;
GRANT INSERT (id, seq, action, subject_kind, subject_id, actor_id, actor_role, payload, ip_address,
              user_agent, correlation_id, success, reason, prev_hash, hash, created_at)
  ON audit_log TO edify_identity_rw;
GRANT INSERT (id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at)
  ON domain_event_log TO edify_identity_rw;

-- One row per successful sign-in, for the Staff Activity Log.
GRANT INSERT (id, user_id, at, role, ip, user_agent, device, active_seconds, last_active_at)
  ON login_event TO edify_identity_rw;

-- The public sign-in figures: counts over the portfolio.
GRANT SELECT (id, deleted_at, operational_status) ON school TO edify_identity_rw;
GRANT SELECT (activity_type, school_id, attended_school_ids, status, fy, deleted_at) ON activity TO edify_identity_rw;
GRANT SELECT (school_id, fy, verification_status, deleted_at) ON ssa_record TO edify_identity_rw;
