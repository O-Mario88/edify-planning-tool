-- Loan origination and servicing workflow (brief: School Loan Origination,
-- Management & Repayment Platform). The money itself (loans, disbursements,
-- installments, verified repayments, reversals) stays in the existing
-- ledger (bt_mfi_loan, bt_loan_disbursement, bt_loan_repayment_installment,
-- bt_repayment_transaction, bt_repayment_allocation), written only by the
-- existing application; these tables hold the workflow around it and the
-- evidence that comes before a posting.

-- The lender's people and their operational roles. Belonging to the lender
-- is bt_mfi_membership's (the existing team record); these are the duties
-- the lender's administrator gives each member on top of it.
CREATE TABLE school_loans.lender_member (
  partner_id text NOT NULL,
  user_id text NOT NULL,
  roles text[] NOT NULL DEFAULT '{}',
  active boolean NOT NULL DEFAULT true,
  updated_by text NOT NULL,
  updated_by_name text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (partner_id, user_id),
  CHECK (roles <@ ARRAY['administrator', 'loan_officer', 'credit_approver', 'finance_officer', 'collections_officer']::text[])
);

CREATE TABLE school_loans.lender_member_event (
  id uuid PRIMARY KEY,
  partner_id text NOT NULL,
  user_id text NOT NULL,
  roles text[] NOT NULL,
  active boolean NOT NULL,
  actor_id text NOT NULL,
  actor_name text NOT NULL DEFAULT '',
  note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Who works a case. A new assignment ends the previous one; none is deleted.
CREATE TABLE school_loans.assignment (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  officer_user_id text NOT NULL,
  officer_name text NOT NULL DEFAULT '',
  assigned_by text NOT NULL,
  assigned_by_name text NOT NULL DEFAULT '',
  assigned_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  end_reason text NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX assignment_one_open ON school_loans.assignment (application_id) WHERE ended_at IS NULL;
CREATE INDEX assignment_officer ON school_loans.assignment (officer_user_id) WHERE ended_at IS NULL;

-- Each contact attempt, as the officer recorded it (a manual entry: the
-- platform places no calls and sends nothing on the officer's behalf here).
CREATE TABLE school_loans.contact_log (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  officer_user_id text NOT NULL,
  officer_name text NOT NULL DEFAULT '',
  contacted_on date NOT NULL,
  method text NOT NULL,
  outcome text NOT NULL,
  notes text NOT NULL DEFAULT '',
  visit_on date,
  next_action_on date,
  document_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (method IN ('phone', 'visit', 'sms', 'email', 'whatsapp', 'other')),
  CHECK (outcome IN ('reached', 'no_answer', 'wrong_number', 'visit_scheduled', 'information_requested', 'other'))
);
CREATE INDEX contact_log_application ON school_loans.contact_log (application_id, created_at);

-- The school assessment: verified facts kept apart from the officer's
-- findings and opinion. It never changes the School Directory.
CREATE TABLE school_loans.assessment (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL UNIQUE REFERENCES school_loans.application (id),
  status text NOT NULL DEFAULT 'not_started',
  visit_on date,
  facts jsonb NOT NULL DEFAULT '{}',
  observations text NOT NULL DEFAULT '',
  strengths text NOT NULL DEFAULT '',
  risks text NOT NULL DEFAULT '',
  documents_reviewed text NOT NULL DEFAULT '',
  outcome text NOT NULL DEFAULT '',
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  CHECK (status IN ('not_started', 'in_progress', 'information_required', 'submitted', 'returned', 'completed'))
);

CREATE TABLE school_loans.assessment_event (
  id uuid PRIMARY KEY,
  assessment_id uuid NOT NULL REFERENCES school_loans.assessment (id),
  from_status text NOT NULL DEFAULT '',
  to_status text NOT NULL,
  snapshot jsonb NOT NULL,
  actor_id text NOT NULL,
  actor_name text NOT NULL DEFAULT '',
  note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

-- The officer's credit recommendation. Each revision is a new version.
CREATE TABLE school_loans.recommendation (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  version integer NOT NULL,
  recommended_amount numeric(20, 2) NOT NULL,
  repayment_capacity_per_term numeric(20, 2),
  rate_percent text NOT NULL DEFAULT '0',
  interest_method text NOT NULL,
  fee_per_installment numeric(20, 2) NOT NULL DEFAULT 0,
  due_dates date[] NOT NULL,
  collateral_summary text NOT NULL DEFAULT '',
  rationale text NOT NULL,
  affordability jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'draft',
  submitted_by text NOT NULL,
  submitted_by_name text NOT NULL DEFAULT '',
  submitted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (application_id, version),
  CHECK (recommended_amount > 0),
  CHECK (interest_method IN ('none', 'flat', 'declining_balance')),
  CHECK (status IN ('draft', 'submitted', 'returned', 'approved', 'declined', 'superseded'))
);

-- What the school is asked to agree to: a frozen copy of the terms and
-- schedule, by version. A response names the exact version and its hash.
CREATE TABLE school_loans.agreement_version (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  recommendation_id uuid NOT NULL REFERENCES school_loans.recommendation (id),
  version integer NOT NULL,
  terms jsonb NOT NULL,
  terms_hash text NOT NULL,
  status text NOT NULL DEFAULT 'issued',
  issued_by text NOT NULL,
  issued_by_name text NOT NULL DEFAULT '',
  issued_at timestamptz NOT NULL DEFAULT now(),
  responded_at timestamptz,
  response_note text NOT NULL DEFAULT '',
  verification jsonb NOT NULL DEFAULT '{}',
  UNIQUE (application_id, version),
  CHECK (status IN ('issued', 'accepted', 'clarification_requested', 'declined', 'superseded'))
);

-- The credit approver's decision on a recommendation.
CREATE TABLE school_loans.approval_decision (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  recommendation_id uuid NOT NULL REFERENCES school_loans.recommendation (id),
  agreement_version_id uuid REFERENCES school_loans.agreement_version (id),
  decision text NOT NULL,
  approved_amount numeric(20, 2),
  rationale text NOT NULL,
  conditions_confirmed boolean NOT NULL DEFAULT false,
  decided_by text NOT NULL,
  decided_by_name text NOT NULL DEFAULT '',
  decided_at timestamptz NOT NULL DEFAULT now(),
  CHECK (decision IN ('approved', 'declined', 'returned')),
  CHECK ((decision = 'approved') = (approved_amount IS NOT NULL))
);

-- The collateral register, item by item, with its history.
CREATE TABLE school_loans.collateral (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  item_type text NOT NULL,
  description text NOT NULL,
  declared_owner text NOT NULL DEFAULT '',
  identification text NOT NULL DEFAULT '',
  estimated_value numeric(20, 2),
  value_date date,
  value_source text NOT NULL DEFAULT '',
  document_type text NOT NULL DEFAULT '',
  custodian text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'proposed',
  release_conditions text NOT NULL DEFAULT '',
  released_on date,
  released_to text NOT NULL DEFAULT '',
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('proposed', 'documents_requested', 'under_verification', 'verified', 'accepted',
    'release_pending', 'released', 'disputed'))
);
CREATE INDEX collateral_application ON school_loans.collateral (application_id);

CREATE TABLE school_loans.collateral_event (
  id uuid PRIMARY KEY,
  collateral_id uuid NOT NULL REFERENCES school_loans.collateral (id),
  from_status text NOT NULL DEFAULT '',
  to_status text NOT NULL,
  note text NOT NULL DEFAULT '',
  document_id uuid,
  recipient_acknowledgment text NOT NULL DEFAULT '',
  actor_id text NOT NULL,
  actor_name text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Evidence uploaded with a payment, a disbursement, an assessment, a
-- collateral item or a contact. Only the lender and authorised staff read
-- it; a school reads only its own receipts.
CREATE TABLE school_loans.document (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  kind text NOT NULL,
  file_name text NOT NULL,
  content_type text NOT NULL,
  size_bytes integer NOT NULL,
  sha256 text NOT NULL,
  content bytea NOT NULL,
  uploaded_by text NOT NULL,
  uploaded_by_kind text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (kind IN ('receipt', 'assessment', 'collateral', 'disbursement', 'contact', 'agreement', 'release')),
  CHECK (content_type IN ('application/pdf', 'image/jpeg', 'image/png')),
  CHECK (size_bytes > 0 AND size_bytes <= 5242880)
);
CREATE INDEX document_application ON school_loans.document (application_id, kind);

-- A payment as reported, before it is money received: recorded, verified
-- or rejected by the lender. Only a verified one is posted to the ledger,
-- under its own idempotency key; the posted transaction is named here.
CREATE TABLE school_loans.payment_evidence (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  mfi_loan_id text NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  amount numeric(20, 2) NOT NULL,
  paid_on date NOT NULL,
  method text NOT NULL,
  transaction_reference text NOT NULL,
  received_by text NOT NULL DEFAULT '',
  notes text NOT NULL DEFAULT '',
  document_id uuid REFERENCES school_loans.document (id),
  source text NOT NULL,
  status text NOT NULL DEFAULT 'verification_pending',
  submitted_by text NOT NULL,
  submitted_by_name text NOT NULL DEFAULT '',
  submitted_at timestamptz NOT NULL DEFAULT now(),
  verified_by text NOT NULL DEFAULT '',
  verified_by_name text NOT NULL DEFAULT '',
  verified_at timestamptz,
  rejection_reason text NOT NULL DEFAULT '',
  ledger_transaction_id text NOT NULL DEFAULT '',
  applied_amount numeric(20, 2),
  excess_amount numeric(20, 2) NOT NULL DEFAULT 0,
  CHECK (amount > 0),
  CHECK (source IN ('lender', 'school')),
  CHECK (method IN ('bank', 'mobile_money', 'cash', 'cheque', 'other')),
  CHECK (status IN ('verification_pending', 'verified', 'rejected')),
  CHECK (status <> 'verified' OR ledger_transaction_id <> '')
);
CREATE UNIQUE INDEX payment_evidence_reference ON school_loans.payment_evidence (mfi_loan_id, lower(transaction_reference))
  WHERE status <> 'rejected';
CREATE INDEX payment_evidence_pending ON school_loans.payment_evidence (application_id) WHERE status = 'verification_pending';

CREATE TABLE school_loans.payment_evidence_event (
  id uuid PRIMARY KEY,
  payment_evidence_id uuid NOT NULL REFERENCES school_loans.payment_evidence (id),
  to_status text NOT NULL,
  note text NOT NULL DEFAULT '',
  actor_id text NOT NULL,
  actor_name text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

-- The application's handover to the existing ledger, and its closure.
ALTER TABLE school_loans.application ADD COLUMN ledger_referral_id text NOT NULL DEFAULT '';
ALTER TABLE school_loans.application ADD COLUMN closure_status text NOT NULL DEFAULT '';
ALTER TABLE school_loans.application ADD COLUMN closed_at timestamptz;
ALTER TABLE school_loans.application ADD COLUMN closure_note text NOT NULL DEFAULT '';

-- A school's private access: a link sent to its director, a one-time code
-- to the director's phone or email, then a short session for one purpose
-- (its agreement or its statement).
CREATE TABLE school_loans.school_access (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  purpose text NOT NULL,
  token_hash text NOT NULL UNIQUE,
  channel text NOT NULL,
  destination text NOT NULL,
  expires_at timestamptz NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  CHECK (purpose IN ('agreement', 'statement')),
  CHECK (channel IN ('sms', 'email'))
);

CREATE TABLE school_loans.school_verification (
  id uuid PRIMARY KEY,
  access_id uuid NOT NULL REFERENCES school_loans.school_access (id),
  code_hash text NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  expires_at timestamptz NOT NULL,
  verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX school_verification_access ON school_loans.school_verification (access_id, created_at);

CREATE TABLE school_loans.school_session (
  id uuid PRIMARY KEY,
  access_id uuid NOT NULL REFERENCES school_loans.school_access (id),
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  purpose text NOT NULL,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Every time a school opened its statement or agreement, and what it did.
CREATE TABLE school_loans.school_access_log (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  session_id uuid,
  action text NOT NULL,
  network_key text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Requests a school sends from its statement: a discrepancy, a question.
CREATE TABLE school_loans.school_request (
  id uuid PRIMARY KEY,
  application_id uuid NOT NULL REFERENCES school_loans.application (id),
  kind text NOT NULL,
  message text NOT NULL,
  status text NOT NULL DEFAULT 'open',
  answered_by text NOT NULL DEFAULT '',
  answer text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  answered_at timestamptz,
  CHECK (kind IN ('discrepancy', 'statement_update', 'contact', 'clarification')),
  CHECK (status IN ('open', 'answered'))
);

-- SMS: one row per message the platform means to send, keyed so a retried
-- schedule never sends twice; its status is only what the provider reported.
CREATE TABLE school_loans.sms_message (
  id uuid PRIMARY KEY,
  application_id uuid REFERENCES school_loans.application (id),
  kind text NOT NULL,
  dedupe_key text NOT NULL UNIQUE,
  recipient text NOT NULL,
  body text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
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
  CHECK (kind IN ('installment_upcoming', 'installment_overdue', 'access_code', 'statement_link', 'agreement_link')),
  CHECK (status IN ('queued', 'submitted', 'delivered', 'failed', 'suppressed'))
);
CREATE INDEX sms_message_due ON school_loans.sms_message (next_attempt_at) WHERE status = 'queued';

CREATE TABLE school_loans.sms_preference (
  phone text PRIMARY KEY,
  opted_out_at timestamptz,
  reason text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON school_loans.lender_member, school_loans.assignment, school_loans.assessment,
  school_loans.recommendation, school_loans.agreement_version, school_loans.collateral,
  school_loans.payment_evidence, school_loans.school_access, school_loans.school_verification,
  school_loans.school_session, school_loans.school_request, school_loans.sms_message,
  school_loans.sms_preference TO edify_loans_rw;
GRANT SELECT, INSERT ON school_loans.lender_member_event, school_loans.contact_log,
  school_loans.assessment_event, school_loans.approval_decision, school_loans.collateral_event,
  school_loans.document, school_loans.payment_evidence_event, school_loans.school_access_log TO edify_loans_rw;
