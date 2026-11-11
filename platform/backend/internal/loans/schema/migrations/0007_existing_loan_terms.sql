-- Loans a lender reported as disbursed before the lender workflow (owner,
-- 2026-11-11: "Lender registers them"). The lender records the loan's
-- existing terms here, entered after the fact with the signed agreement, so
-- the loan can be registered in the loan ledger and its schedule posted. No
-- recommendation or credit decision is invented for it. Additive only.

CREATE TABLE school_loans.existing_loan_terms (
  application_id uuid PRIMARY KEY REFERENCES school_loans.application (id),
  external_reference text NOT NULL,
  approved_amount numeric(20, 2) NOT NULL,
  rate_percent text NOT NULL DEFAULT '0',
  interest_method text NOT NULL,
  fee_per_installment numeric(20, 2) NOT NULL DEFAULT 0,
  due_dates date[] NOT NULL,
  approved_on date NOT NULL,
  agreement_document_id uuid NOT NULL REFERENCES school_loans.document (id),
  recorded_by text NOT NULL,
  recorded_by_name text NOT NULL DEFAULT '',
  recorded_at timestamptz NOT NULL DEFAULT now(),
  CHECK (approved_amount > 0),
  CHECK (fee_per_installment >= 0),
  CHECK (cardinality(due_dates) > 0),
  CHECK (interest_method IN ('none', 'flat', 'declining_balance'))
);

GRANT SELECT, INSERT ON school_loans.existing_loan_terms TO edify_loans_rw;
