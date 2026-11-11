-- The School Loan Application Portal's own schema and the roles around it.
-- Applied by apply-roles.sh to a development, test or staging database;
-- never to production (a production rollout needs its own approval, backup
-- and recovery plan).
--
-- The portal's records (public applications, their history and follow-ups,
-- the lender delivery outbox, lender access) live in school_loans, which Go
-- owns. Nothing here touches a table, column, index or constraint of the
-- existing application, and no row is read or written. The existing loan
-- workflow (bt_loan_application, bt_mfi_loan, the MFI portal) keeps working
-- exactly as it does; the portal only reads it.
--
--   edify_loans_owner  NOLOGIN. Owns school_loans; migrations run as it
--                      (schemactl migrate does SET ROLE). No privilege on any
--                      existing table.
--   edify_loans_rw     NOLOGIN. The gateway's reads and writes on the
--                      portal's tables, granted table by table by the
--                      migrations themselves.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_loans_owner') THEN
    CREATE ROLE edify_loans_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_loans_rw') THEN
    CREATE ROLE edify_loans_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS school_loans AUTHORIZATION edify_loans_owner;

REVOKE ALL ON SCHEMA public FROM edify_loans_owner;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_loans_owner;

GRANT edify_loans_owner TO CURRENT_USER;

GRANT USAGE ON SCHEMA school_loans TO edify_loans_rw;
GRANT edify_loans_rw TO edify_gateway;

-- internal/loans reads, never writes, the existing records it needs.
-- The Partner Directory's Loan Partners and the lenders they are in the
-- loan workflow (apps.partners.loan_partner links the two).
GRANT SELECT (id, name, partner_role, active_status, loan_lender_id, deleted_at)
  ON partner TO edify_gateway_ro;
GRANT SELECT (id, name, active, data_sharing_agreement_active, country_code, deleted_at)
  ON bt_mfi_organization TO edify_gateway_ro;
-- A lender's own staff, who sign in to Edify (MfiPartnerAdmin, MfiLoanOfficer).
GRANT SELECT (user_id, mfi_id, role, active) ON bt_mfi_membership TO edify_gateway_ro;
-- The places the form offers, each under its parent.
GRANT SELECT (district_id) ON sub_county TO edify_gateway_ro;
GRANT SELECT (sub_county_id) ON parish TO edify_gateway_ro;
-- A school's loan history on its profile: the existing web-form applications
-- and the loans its lenders registered.
GRANT SELECT (id, school_id, purpose_id, preferred_mfi_id, requested_amount, currency, status,
  submitted_at, deleted_at)
  ON bt_loan_application TO edify_gateway_ro;
GRANT SELECT (id, school_id, mfi_id, purpose_id, status, approved_amount, disbursed_amount,
  currency, disbursement_date, deleted_at)
  ON bt_mfi_loan TO edify_gateway_ro;
GRANT SELECT (id, code, label) ON bt_loan_purpose TO edify_gateway_ro;

-- Origination and servicing (2026-11-11): the platform computes each loan's
-- position and statement from the existing ledger's postings, read only.
-- The postings themselves are written only by the existing application.
GRANT SELECT (id, mfi_id, school_id, referral_id, facility_id, purpose_id, external_loan_reference,
  assigned_officer_reference, requested_amount, approved_amount, disbursed_amount, term_months, status,
  currency, deleted_at)
  ON bt_mfi_loan TO edify_gateway_ro;
GRANT SELECT (id, loan_id, amount, disbursed_on, value_date, external_reference, bank_reference, sequence)
  ON bt_loan_disbursement TO edify_gateway_ro;
GRANT SELECT (id, disbursement_id, reversed_at) ON bt_loan_disbursement_reversal TO edify_gateway_ro;
GRANT SELECT (id, loan_id, schedule_version, installment_number, due_date, principal_due, interest_due, fee_due)
  ON bt_loan_repayment_installment TO edify_gateway_ro;
GRANT SELECT (id, loan_id, kind, reversal_of_id, amount, received_on, value_date, external_reference,
  evidence_reference, posted_at)
  ON bt_repayment_transaction TO edify_gateway_ro;
GRANT SELECT (id, transaction_id, installment_id, component, amount) ON bt_repayment_allocation TO edify_gateway_ro;
-- Handing an approved application over to the ledger: the school's open
-- Business Transformation case, its referral, and the lender's facilities.
GRANT SELECT (id, school_id, status, closed_at, deleted_at) ON bt_case TO edify_gateway_ro;
GRANT SELECT (id, case_id, mfi_id, purpose_id, status, deleted_at) ON bt_finance_referral TO edify_gateway_ro;
GRANT SELECT (id, mfi_id, name, status, currency, approved_amount) ON bt_funding_facility TO edify_gateway_ro;
GRANT SELECT (id, loan_id, facility_id, amount, status) ON bt_funding_facility_allocation TO edify_gateway_ro;
GRANT SELECT (active) ON bt_loan_purpose TO edify_gateway_ro;
GRANT SELECT (officer_reference) ON bt_mfi_membership TO edify_gateway_ro;
-- The existing ledger's own conditions for a first disbursement: a purpose
-- plan that adds up to the approved amount and an enrolment baseline.
GRANT SELECT (id, loan_id, planned_amount) ON bt_loan_purpose_allocation TO edify_gateway_ro;
GRANT SELECT (id, loan_id, kind, as_of_date) ON bt_enrolment_snapshot TO edify_gateway_ro;
