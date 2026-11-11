-- Sharing the loan application (2026-11-11): lender-specific and personal
-- referral links, editable share messages, share counts, and account-free
-- application tracking. Additive only: nothing existing is altered beyond
-- new nullable or defaulted columns.

-- A shareable link with an opaque id. A partner link names one lender and
-- may fix it as the recipient; a referral link only says who shared it
-- (and, for a Cluster Leader, from which cluster), never who applied.
CREATE TABLE school_loans.share_link (
  id text PRIMARY KEY,
  kind text NOT NULL,
  partner_id text,
  lock_partner boolean NOT NULL DEFAULT true,
  cluster_id text,
  label text NOT NULL DEFAULT '',
  created_by text NOT NULL,
  created_by_name text NOT NULL DEFAULT '',
  created_role text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  revoked_by text,
  CHECK (kind IN ('partner', 'referral')),
  CHECK ((kind = 'partner') = (partner_id IS NOT NULL)),
  CHECK (id ~ '^[A-Za-z0-9_-]{16,64}$'),
  CHECK ((revoked_at IS NULL) = (revoked_by IS NULL))
);
-- One live link per lender, and one live referral link per person, so a
-- link once printed or shared stays the same.
CREATE UNIQUE INDEX share_link_live_partner ON school_loans.share_link (partner_id)
  WHERE kind = 'partner' AND revoked_at IS NULL;
CREATE UNIQUE INDEX share_link_live_referral ON school_loans.share_link (created_by)
  WHERE kind = 'referral' AND revoked_at IS NULL;

ALTER TABLE school_loans.application ADD COLUMN share_link_id text REFERENCES school_loans.share_link (id);
CREATE INDEX application_share_link ON school_loans.application (share_link_id) WHERE share_link_id IS NOT NULL;

ALTER TABLE school_loans.invitation ADD COLUMN source text NOT NULL DEFAULT '',
  ADD COLUMN campaign text NOT NULL DEFAULT '',
  ADD COLUMN revoked_by text,
  ADD COLUMN revoke_reason text NOT NULL DEFAULT '';
CREATE INDEX invitation_school ON school_loans.invitation (school_id, created_at);

-- Who shared which link, how. Counts only: no applicant is in it.
CREATE TABLE school_loans.share_event (
  id uuid PRIMARY KEY,
  kind text NOT NULL,
  channel text NOT NULL DEFAULT '',
  link_kind text NOT NULL,
  share_link_id text REFERENCES school_loans.share_link (id),
  invitation_id uuid REFERENCES school_loans.invitation (id),
  actor_id text NOT NULL,
  actor_role text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (kind IN ('generated', 'shared', 'revoked')),
  CHECK (channel IN ('', 'whatsapp', 'sms', 'email', 'copy', 'native', 'qr')),
  CHECK (link_kind IN ('universal', 'invitation', 'partner', 'referral'))
);
CREATE INDEX share_event_created ON school_loans.share_event (created_at);

-- The share messages Edify approves. The default text lives in the code;
-- a row here replaces it.
CREATE TABLE school_loans.share_template (
  channel text PRIMARY KEY,
  subject text NOT NULL DEFAULT '',
  body text NOT NULL,
  updated_by text NOT NULL,
  updated_by_name text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (channel IN ('whatsapp', 'sms', 'email')),
  CHECK (position('{application_link}' in body) > 0)
);

-- Account-free application tracking: the reference and the director's phone
-- ask for a code, sent only to the phone on the application; a right code
-- opens a short session that shows the application's progress, nothing of
-- any loan statement.
CREATE TABLE school_loans.tracking_verification (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  code_hash text NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  expires_at timestamptz NOT NULL,
  verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (attempts >= 0)
);
CREATE INDEX tracking_verification_application ON school_loans.tracking_verification (application_id, created_at);

CREATE TABLE school_loans.tracking_session (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON school_loans.share_link, school_loans.share_template, school_loans.tracking_verification,
  school_loans.tracking_session TO edify_loans_rw;
GRANT SELECT, INSERT ON school_loans.share_event TO edify_loans_rw;
