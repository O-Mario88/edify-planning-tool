-- A staff alert or reminder is addressed to a person, not a lender: name
-- them in a column of their own.
ALTER TABLE school_loans.delivery_task ADD COLUMN recipient_user_id text NOT NULL DEFAULT '';
