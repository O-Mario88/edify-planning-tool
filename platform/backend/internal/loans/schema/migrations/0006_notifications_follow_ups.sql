-- Staff loan tracking (2026-11-11): one notification history per school and
-- loan, shared by Edify staff, lenders and the weekly reminders, with its
-- own delivery queue and attempt log; and fuller follow-up records. Additive
-- only.

CREATE TABLE school_loans.notification (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  school_id text,
  mfi_loan_id text,
  type text NOT NULL,
  channel text NOT NULL DEFAULT 'sms',
  recipient text NOT NULL,
  recipient_name text NOT NULL DEFAULT '',
  body text NOT NULL,
  template_version text NOT NULL,
  -- Who started it: a person, or 'system' for the weekly reminders.
  triggered_by text NOT NULL,
  triggered_by_name text NOT NULL DEFAULT '',
  sender_role text NOT NULL,
  -- 'Edify' or the lender's name: whose message it is.
  sending_organisation text NOT NULL,
  -- Set when a person sent it inside the cooldown, with their reason.
  exception_reason text NOT NULL DEFAULT '',
  related_follow_up_id uuid REFERENCES school_loans.follow_up (id),
  dedupe_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'queued',
  failure_category text NOT NULL DEFAULT '',
  provider text NOT NULL DEFAULT '',
  provider_message_id text NOT NULL DEFAULT '',
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  lease_until timestamptz,
  last_error text NOT NULL DEFAULT '',
  submitted_at timestamptz,
  delivered_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (type IN ('application_received', 'application_under_review', 'information_required', 'assessment_appointment',
    'agreement_review', 'disbursement_confirmation', 'installment_upcoming', 'payment_due', 'payment_overdue',
    'receipt_acknowledgment', 'payment_verified', 'loan_settled', 'collateral_release', 'general_follow_up',
    'statement_link')),
  CHECK (channel IN ('sms', 'email')),
  CHECK (status IN ('queued', 'submitted', 'delivered', 'failed', 'suppressed')),
  CHECK (failure_category IN ('', 'provider_refused', 'provider_unreachable', 'undeliverable', 'opted_out', 'no_provider')),
  CHECK (attempts >= 0)
);
CREATE INDEX notification_application ON school_loans.notification (application_id, created_at);
CREATE INDEX notification_due ON school_loans.notification (next_attempt_at) WHERE status = 'queued';
CREATE INDEX notification_provider ON school_loans.notification (provider_message_id) WHERE provider_message_id <> '';

-- Every try to hand a notification to the provider, kept.
CREATE TABLE school_loans.notification_attempt (
  id uuid PRIMARY KEY,
  notification_id uuid NOT NULL REFERENCES school_loans.notification (id),
  attempted_at timestamptz NOT NULL DEFAULT now(),
  outcome text NOT NULL,
  error text NOT NULL DEFAULT '',
  CHECK (outcome IN ('submitted', 'retry', 'failed', 'delivered', 'undeliverable'))
);
CREATE INDEX notification_attempt_notification ON school_loans.notification_attempt (notification_id, attempted_at);

-- Follow-ups by any authorised Edify staff member, not only the BTO. The
-- staff fields already there keep who recorded it, unchanged if the school
-- later moves to another portfolio.
ALTER TABLE school_loans.follow_up ADD COLUMN school_id text,
  ADD COLUMN contacted_person text NOT NULL DEFAULT '',
  ADD COLUMN reason text NOT NULL DEFAULT '',
  ADD COLUMN school_feedback text NOT NULL DEFAULT '',
  ADD COLUMN reported_issue text NOT NULL DEFAULT '',
  ADD COLUMN escalation_target text NOT NULL DEFAULT '',
  ADD COLUMN responsible_user_id text NOT NULL DEFAULT '',
  -- "Payment reported by school — awaiting lender verification": a note,
  -- never a payment. Balances move only on the lender's verification.
  ADD COLUMN payment_reported boolean NOT NULL DEFAULT false,
  ADD COLUMN reported_amount numeric(18, 2),
  ADD COLUMN reported_paid_on date;
CREATE INDEX follow_up_application_next ON school_loans.follow_up (application_id, next_follow_up_on);

GRANT SELECT, INSERT, UPDATE ON school_loans.notification TO edify_loans_rw;
GRANT SELECT, INSERT ON school_loans.notification_attempt TO edify_loans_rw;
