-- The School Loan Application Portal's own records (brief: public school
-- loan application and lending-partner tracking). Every table is in
-- school_loans; the existing application's schools, partners, lenders and
-- loans are referred to by their ids and only ever read, so there are no
-- foreign keys out of this schema.

-- How a Loan Partner of the Partner Directory receives referrals: switched
-- on by the Country Director, with a receiving address the lender itself has
-- confirmed. A changed address is unconfirmed until the lender confirms it.
CREATE TABLE school_loans.lender_channel (
  partner_id text PRIMARY KEY,
  referrals_enabled boolean NOT NULL DEFAULT false,
  delivery_email text NOT NULL DEFAULT '',
  confirmed_email text NOT NULL DEFAULT '',
  confirmed_at timestamptz,
  confirm_token_hash text UNIQUE,
  confirm_expires_at timestamptz,
  description text NOT NULL DEFAULT '',
  updated_by text NOT NULL,
  updated_by_name text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (length(description) <= 280)
);

CREATE TABLE school_loans.lender_channel_event (
  id uuid PRIMARY KEY,
  partner_id text NOT NULL,
  kind text NOT NULL,
  actor_id text NOT NULL,
  actor_name text NOT NULL DEFAULT '',
  note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX lender_channel_event_partner ON school_loans.lender_channel_event (partner_id, created_at);

-- A school-specific invitation link. It names the school the link was sent
-- to; it proves nothing about who opens it.
CREATE TABLE school_loans.invitation (
  id uuid PRIMARY KEY,
  token_hash text NOT NULL UNIQUE,
  school_id text NOT NULL,
  school_name text NOT NULL,
  created_by text NOT NULL,
  created_by_name text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);

CREATE TABLE school_loans.application (
  id uuid PRIMARY KEY,
  reference text NOT NULL UNIQUE,
  idempotency_key text NOT NULL UNIQUE,
  receipt_token_hash text NOT NULL UNIQUE,
  receipt_expires_at timestamptz NOT NULL,
  source text NOT NULL,
  invitation_id uuid REFERENCES school_loans.invitation (id),

  school_name text NOT NULL,
  director_name text NOT NULL,
  director_phone text NOT NULL,
  director_email text NOT NULL DEFAULT '',
  director_religion text NOT NULL DEFAULT '',

  district_id text NOT NULL DEFAULT '',
  district_name text NOT NULL,
  sub_county_id text NOT NULL DEFAULT '',
  sub_county_name text NOT NULL,
  parish_id text NOT NULL DEFAULT '',
  parish_name text NOT NULL,
  village_name text NOT NULL,

  boys integer NOT NULL,
  girls integer NOT NULL,
  total_enrollment integer GENERATED ALWAYS AS (boys + girls) STORED,
  average_fees_collected_ugx numeric(18, 0) NOT NULL,

  purpose_code text NOT NULL,
  purpose_label text NOT NULL,
  purpose_other text NOT NULL DEFAULT '',
  purpose_details text NOT NULL DEFAULT '',
  requested_amount_ugx numeric(18, 0) NOT NULL,
  preferred_term_months integer,

  partner_id text NOT NULL,
  lender_id text NOT NULL,
  lender_name text NOT NULL,

  consent_version text NOT NULL,
  consent_recorded_at timestamptz NOT NULL,

  school_match_status text NOT NULL,
  school_id text,
  match_method text NOT NULL DEFAULT '',
  matched_by text NOT NULL DEFAULT '',
  matched_at timestamptz,

  status text NOT NULL,
  delivery_status text NOT NULL,
  responsible_bto_id text NOT NULL DEFAULT '',
  responsible_bto_name text NOT NULL DEFAULT '',
  next_follow_up_on date,
  last_follow_up_at timestamptz,
  lender_received_at timestamptz,
  decided_at timestamptz,

  approved_amount_ugx numeric(18, 0),
  disbursed_amount_ugx numeric(18, 0),
  disbursement_date date,
  agreed_term_months integer,
  interest_rate_text text NOT NULL DEFAULT '',
  disbursement_reference text NOT NULL DEFAULT '',
  linked_mfi_loan_id text NOT NULL DEFAULT '',

  submitted_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),

  CHECK (source IN ('public_link', 'invitation')),
  CHECK (boys >= 0 AND girls >= 0),
  CHECK (average_fees_collected_ugx >= 0),
  CHECK (requested_amount_ugx > 0),
  CHECK (preferred_term_months IS NULL OR preferred_term_months BETWEEN 1 AND 120),
  CHECK (agreed_term_months IS NULL OR agreed_term_months BETWEEN 1 AND 240),
  CHECK (approved_amount_ugx IS NULL OR approved_amount_ugx > 0),
  CHECK (disbursed_amount_ugx IS NULL OR disbursed_amount_ugx > 0),
  CHECK (school_match_status IN ('matched', 'needs_review', 'unmatched', 'not_in_directory')),
  CHECK ((school_match_status = 'matched') = (school_id IS NOT NULL)),
  CHECK (status IN ('submitted', 'awaiting_lender_receipt', 'received_by_lender', 'under_review',
    'information_requested', 'approved', 'declined', 'disbursed', 'closed', 'withdrawn')),
  CHECK (delivery_status IN ('queued', 'sent', 'failed', 'opened_by_lender')),
  CHECK (status <> 'disbursed' OR (disbursed_amount_ugx IS NOT NULL AND disbursement_date IS NOT NULL))
);
CREATE INDEX application_partner_status ON school_loans.application (partner_id, status);
CREATE INDEX application_submitted ON school_loans.application (submitted_at);
CREATE INDEX application_school ON school_loans.application (school_id) WHERE school_id IS NOT NULL;
CREATE INDEX application_follow_up ON school_loans.application (next_follow_up_on)
  WHERE status NOT IN ('declined', 'disbursed', 'closed', 'withdrawn');
CREATE INDEX application_duplicate_check ON school_loans.application (director_phone, submitted_at);

-- Every material change: who, when, and from where (applicant, staff,
-- lender, system). Rows are only ever added.
CREATE TABLE school_loans.application_event (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  kind text NOT NULL,
  actor_kind text NOT NULL,
  actor_id text NOT NULL DEFAULT '',
  actor_name text NOT NULL DEFAULT '',
  from_status text NOT NULL DEFAULT '',
  to_status text NOT NULL DEFAULT '',
  note text NOT NULL DEFAULT '',
  evidence text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (actor_kind IN ('applicant', 'staff', 'lender', 'system'))
);
CREATE INDEX application_event_timeline ON school_loans.application_event (application_id, created_at);

-- A staff follow-up with the lender. A follow-up never changes the
-- application's status: only the lender, or an evidence-backed correction,
-- does that.
CREATE TABLE school_loans.follow_up (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  staff_id text NOT NULL,
  staff_name text NOT NULL DEFAULT '',
  staff_active_role text NOT NULL DEFAULT '',
  followed_up_on date NOT NULL,
  channel text NOT NULL,
  lender_partner_id text NOT NULL DEFAULT '',
  notes text NOT NULL,
  lender_feedback text NOT NULL DEFAULT '',
  next_action text NOT NULL DEFAULT '',
  next_follow_up_on date,
  document_reference text NOT NULL DEFAULT '',
  is_oversight boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX follow_up_application ON school_loans.follow_up (application_id, created_at);

-- The outbox: a task is written in the same transaction as the record it is
-- about, so an accepted application is never lost between storage and the
-- lender's notification. The delivery worker leases and sends it.
CREATE TABLE school_loans.delivery_task (
  id uuid PRIMARY KEY,
  kind text NOT NULL,
  dedupe_key text NOT NULL UNIQUE,
  application_id uuid REFERENCES school_loans.application (id),
  partner_id text NOT NULL DEFAULT '',
  recipient_email text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'pending',
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  lease_until timestamptz,
  last_error text NOT NULL DEFAULT '',
  provider_message_id text NOT NULL DEFAULT '',
  sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (kind IN ('lender_referral', 'staff_alert', 'follow_up_reminder')),
  CHECK (status IN ('pending', 'sent', 'failed', 'cancelled'))
);
CREATE INDEX delivery_task_due ON school_loans.delivery_task (next_attempt_at) WHERE status = 'pending';
CREATE INDEX delivery_task_application ON school_loans.delivery_task (application_id);

-- A lender's way in from an email: the link names a lender (and the
-- referral it was sent about) but opens nothing until a code sent to the
-- lender's confirmed address is entered; then a short session is issued.
CREATE TABLE school_loans.lender_access (
  id uuid PRIMARY KEY,
  partner_id text NOT NULL,
  application_id uuid REFERENCES school_loans.application (id),
  token_hash text NOT NULL UNIQUE,
  email text NOT NULL,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE school_loans.lender_verification (
  id uuid PRIMARY KEY,
  access_id uuid NOT NULL REFERENCES school_loans.lender_access (id),
  code_hash text NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  expires_at timestamptz NOT NULL,
  verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX lender_verification_access ON school_loans.lender_verification (access_id, created_at);

CREATE TABLE school_loans.lender_session (
  id uuid PRIMARY KEY,
  partner_id text NOT NULL,
  email text NOT NULL,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON school_loans.lender_channel, school_loans.invitation,
  school_loans.application, school_loans.delivery_task, school_loans.lender_access,
  school_loans.lender_verification, school_loans.lender_session TO edify_loans_rw;
GRANT SELECT, INSERT ON school_loans.lender_channel_event, school_loans.application_event,
  school_loans.follow_up TO edify_loans_rw;
