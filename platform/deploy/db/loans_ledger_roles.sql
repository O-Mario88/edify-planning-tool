-- Least-privilege role and SECURITY DEFINER functions for the native Go loan
-- ledger writer (Batch 10 — replaces loans.LedgerClient HTTP relay to Django).
--
-- Enforces idempotency_key deduplication on disbursements, repayments, and
-- reversals so duplicated callbacks or retries apply each monetary effect ONCE.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_loans_ledger_owner') THEN
        CREATE ROLE edify_loans_ledger_owner NOLOGIN NOINHERIT;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO edify_loans_ledger_owner;
GRANT SELECT ON bt_case, bt_funding_facility, bt_mfi_organization, bt_loan_purpose TO edify_loans_ledger_owner;
GRANT SELECT, INSERT, UPDATE ON
    bt_finance_referral,
    bt_mfi_loan,
    bt_funding_facility_allocation,
    bt_loan_disbursement,
    bt_loan_repayment_installment,
    bt_repayment_transaction,
    bt_repayment_allocation,
    bt_mfi_membership,
    bt_loan_purpose_allocation,
    bt_enrolment_snapshot
TO edify_loans_ledger_owner;

CREATE SCHEMA IF NOT EXISTS gateway_loans_ledger AUTHORIZATION edify_loans_ledger_owner;
REVOKE ALL ON SCHEMA gateway_loans_ledger FROM PUBLIC;
GRANT USAGE ON SCHEMA gateway_loans_ledger TO edify_gateway;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.create_referral(
    p_case_id text, p_mfi_id text, p_purpose_id text,
    p_amount numeric, p_intended_use text, p_consent timestamptz, p_actor text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id text := 'ref_' || substr(md5(p_case_id || ':' || p_mfi_id || ':' || clock_timestamp()::text), 1, 22);
BEGIN
    INSERT INTO public.bt_finance_referral (
        id, case_id, mfi_id, purpose_id, requested_amount, currency,
        intended_use, consent_recorded_at, status, referred_by, referred_at,
        decision_reason, source, environment, created_at, updated_at
    ) VALUES (
        v_id, p_case_id, p_mfi_id, p_purpose_id, p_amount, 'UGX',
        COALESCE(p_intended_use, ''), p_consent, 'referred', p_actor, NOW(),
        '', 'gateway', 'development', NOW(), NOW()
    );
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.register_loan(
    p_referral_id text, p_external_ref text, p_officer_ref text,
    p_approved numeric, p_requested numeric, p_term_months int, p_actor text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id        text;
    v_school_id  text;
    v_mfi_id     text;
    v_case_id    text;
    v_purpose_id text;
BEGIN
    SELECT l.id INTO v_id FROM public.bt_mfi_loan l
    WHERE l.referral_id = p_referral_id AND l.external_loan_reference = p_external_ref AND l.deleted_at IS NULL
    LIMIT 1;
    IF v_id IS NOT NULL THEN
        RETURN v_id;
    END IF;
    SELECT c.school_id, r.mfi_id, r.case_id, r.purpose_id
      INTO v_school_id, v_mfi_id, v_case_id, v_purpose_id
    FROM public.bt_finance_referral r JOIN public.bt_case c ON c.id = r.case_id
    WHERE r.id = p_referral_id;
    IF v_school_id IS NULL THEN
        RAISE EXCEPTION 'loans: referral % not found', p_referral_id;
    END IF;
    v_id := 'ln_' || substr(md5(p_referral_id || ':' || p_external_ref || ':' || clock_timestamp()::text), 1, 22);
    INSERT INTO public.bt_mfi_loan (
        id, referral_id, school_id, mfi_id, case_id, purpose_id, external_loan_reference,
        assigned_officer_reference, requested_amount, approved_amount, term_months,
        currency, repayment_frequency, status, registered_by,
        salesforce_status, salesforce_confirmation_note, salesforce_return_note, salesforce_return_reason,
        ia_validation_status, ia_return_reason, impact_status, default_reason,
        source, environment, created_at, updated_at
    ) VALUES (
        v_id, p_referral_id, v_school_id, v_mfi_id, v_case_id, v_purpose_id, p_external_ref,
        COALESCE(p_officer_ref, ''), p_requested, p_approved, NULLIF(p_term_months, 0),
        'UGX', 'monthly', 'processing', COALESCE(NULLIF(p_actor, ''), 'system'),
        'pending', '', '', '',
        'pending', '', 'pending', '',
        'gateway', 'development', NOW(), NOW()
    );
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.reserve_facility(
    p_facility_id text, p_loan_id text, p_amount numeric, p_key text, p_actor text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id text;
BEGIN
    SELECT id INTO v_id FROM public.bt_funding_facility_allocation
    WHERE idempotency_key = p_key
    LIMIT 1;
    IF v_id IS NOT NULL THEN
        RETURN v_id;
    END IF;
    v_id := 'fal_' || substr(md5(p_facility_id || ':' || p_loan_id || ':' || p_key), 1, 22);
    INSERT INTO public.bt_funding_facility_allocation (
        id, facility_id, loan_id, amount, status, idempotency_key,
        reserved_by, reserved_at, release_reason, capital_source,
        created_at, updated_at
    ) VALUES (
        v_id, p_facility_id, p_loan_id, p_amount, 'reserved', p_key,
        COALESCE(NULLIF(p_actor, ''), 'system'), NOW(), '', 'edify_facility',
        NOW(), NOW()
    )
    ON CONFLICT DO NOTHING;
    SELECT id INTO v_id FROM public.bt_funding_facility_allocation
    WHERE idempotency_key = p_key
    LIMIT 1;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.post_disbursement(
    p_loan_id text, p_key text, p_ext_ref text, p_bank_ref text,
    p_amount numeric, p_seq int, p_disbursed date, p_value date, p_actor text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id       text;
    v_alloc_id text;
BEGIN
    SELECT id INTO v_id FROM public.bt_loan_disbursement WHERE idempotency_key = p_key LIMIT 1;
    IF v_id IS NOT NULL THEN
        RETURN v_id;
    END IF;
    SELECT id INTO v_alloc_id FROM public.bt_funding_facility_allocation
    WHERE loan_id = p_loan_id ORDER BY created_at DESC LIMIT 1;
    IF v_alloc_id IS NULL THEN
        RAISE EXCEPTION 'loans: no facility allocation found for loan %', p_loan_id;
    END IF;
    v_id := 'dsb_' || substr(md5(p_loan_id || ':' || p_key), 1, 22);
    INSERT INTO public.bt_loan_disbursement (
        id, loan_id, allocation_id, sequence, external_reference, idempotency_key,
        amount, disbursed_on, value_date, bank_reference, confirmed_by, confirmed_at,
        capital_source, created_at, updated_at
    ) VALUES (
        v_id, p_loan_id, v_alloc_id, p_seq, p_ext_ref, p_key,
        p_amount, p_disbursed, p_value, COALESCE(p_bank_ref, ''), p_actor, NOW(),
        'edify_facility', NOW(), NOW()
    )
    ON CONFLICT DO NOTHING;
    SELECT id INTO v_id FROM public.bt_loan_disbursement WHERE idempotency_key = p_key LIMIT 1;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.post_schedule(
    p_loan_id text, p_version int, p_rows jsonb, p_actor text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_item jsonb;
    v_id   text;
BEGIN
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_rows) LOOP
        v_id := 'ins_' || substr(md5(p_loan_id || ':' || p_version::text || ':' || (v_item->>'number')), 1, 22);
        INSERT INTO public.bt_loan_repayment_installment (
            id, loan_id, schedule_version, installment_number, due_date,
            principal_due, interest_due, fee_due, created_at, updated_at
        ) VALUES (
            v_id, p_loan_id, p_version, (v_item->>'number')::int, (v_item->>'due_date')::date,
            (v_item->>'principal')::numeric, (v_item->>'interest')::numeric, (v_item->>'fee')::numeric,
            NOW(), NOW()
        )
        ON CONFLICT (id) DO NOTHING;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.post_repayment(
    p_loan_id text, p_key text, p_ext_ref text, p_evidence text,
    p_amount numeric, p_received date, p_value date, p_allocs jsonb, p_actor text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id   text;
    v_item jsonb;
    v_aid  text;
BEGIN
    SELECT id INTO v_id FROM public.bt_repayment_transaction WHERE idempotency_key = p_key LIMIT 1;
    IF v_id IS NOT NULL THEN
        RETURN v_id;
    END IF;
    v_id := 'rep_' || substr(md5(p_loan_id || ':' || p_key), 1, 22);
    INSERT INTO public.bt_repayment_transaction (
        id, loan_id, kind, external_reference, idempotency_key,
        amount, received_on, value_date, evidence_reference,
        posted_by, posted_at, reason, created_at, updated_at
    ) VALUES (
        v_id, p_loan_id, 'payment', p_ext_ref, p_key,
        p_amount, p_received, p_value, COALESCE(p_evidence, ''),
        p_actor, NOW(), '', NOW(), NOW()
    )
    ON CONFLICT DO NOTHING;
    SELECT id INTO v_id FROM public.bt_repayment_transaction WHERE idempotency_key = p_key LIMIT 1;
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_allocs) LOOP
        v_aid := 'ral_' || substr(md5(v_id || ':' || (v_item->>'installment_id') || ':' || (v_item->>'component')), 1, 22);
        INSERT INTO public.bt_repayment_allocation (
            id, transaction_id, installment_id, component, amount, created_at, updated_at
        ) VALUES (
            v_aid, v_id, v_item->>'installment_id', v_item->>'component', (v_item->>'amount')::numeric, NOW(), NOW()
        )
        ON CONFLICT (id) DO NOTHING;
    END LOOP;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.reverse_repayment(
    p_tx_id text, p_key text, p_reason text, p_ext_ref text, p_evidence text, p_actor text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id      text;
    v_loan_id text;
    v_amount  numeric;
    v_rec     date;
    v_val     date;
BEGIN
    SELECT id INTO v_id FROM public.bt_repayment_transaction WHERE idempotency_key = p_key LIMIT 1;
    IF v_id IS NOT NULL THEN
        RETURN v_id;
    END IF;
    SELECT loan_id, amount, received_on, value_date INTO v_loan_id, v_amount, v_rec, v_val
    FROM public.bt_repayment_transaction WHERE id = p_tx_id;
    IF v_loan_id IS NULL THEN
        RAISE EXCEPTION 'loans: transaction % not found', p_tx_id;
    END IF;
    v_id := 'rev_' || substr(md5(p_tx_id || ':' || p_key), 1, 22);
    INSERT INTO public.bt_repayment_transaction (
        id, loan_id, kind, external_reference, idempotency_key,
        amount, received_on, value_date, evidence_reference,
        posted_by, posted_at, reason, reversal_of_id, created_at, updated_at
    ) VALUES (
        v_id, v_loan_id, 'reversal', p_ext_ref, p_key,
        v_amount, v_rec, v_val, COALESCE(p_evidence, ''),
        p_actor, NOW(), COALESCE(p_reason, ''), p_tx_id, NOW(), NOW()
    )
    ON CONFLICT DO NOTHING;
    SELECT id INTO v_id FROM public.bt_repayment_transaction WHERE idempotency_key = p_key LIMIT 1;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.set_officer_reference(
    p_mfi_id text, p_user_id text, p_ref text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    UPDATE public.bt_mfi_membership
    SET officer_reference = p_ref, updated_at = NOW()
    WHERE mfi_id = p_mfi_id AND user_id = p_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.set_purpose_plan(
    p_loan_id text, p_lines jsonb, p_actor text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_item jsonb;
    v_id   text;
BEGIN
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_lines) LOOP
        v_id := 'pal_' || substr(md5(p_loan_id || ':' || (v_item->>'purpose_id')), 1, 22);
        INSERT INTO public.bt_loan_purpose_allocation (
            id, loan_id, purpose_id, planned_amount, intended_output, created_at, updated_at
        ) VALUES (
            v_id, p_loan_id, v_item->>'purpose_id', (v_item->>'amount')::numeric,
            COALESCE(v_item->>'intended_output', ''), NOW(), NOW()
        )
        ON CONFLICT (id) DO UPDATE
        SET planned_amount = EXCLUDED.planned_amount, intended_output = EXCLUDED.intended_output, updated_at = NOW();
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_loans_ledger.record_enrolment_baseline(
    p_loan_id text, p_learners int, p_as_of date, p_cohort text, p_evidence text, p_actor text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id text := 'enr_' || substr(md5(p_loan_id || ':baseline:' || p_as_of::text), 1, 22);
BEGIN
    INSERT INTO public.bt_enrolment_snapshot (
        id, loan_id, kind, learner_count, as_of_date, cohort_definition,
        evidence_reference, status, recorded_by, created_at, updated_at
    ) VALUES (
        v_id, p_loan_id, 'baseline', p_learners, p_as_of, COALESCE(p_cohort, ''),
        COALESCE(p_evidence, ''), 'reported', p_actor, NOW(), NOW()
    )
    ON CONFLICT (id) DO NOTHING;
END;
$$;

ALTER FUNCTION gateway_loans_ledger.create_referral(text, text, text, numeric, text, timestamptz, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.register_loan(text, text, text, numeric, numeric, int, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.reserve_facility(text, text, numeric, text, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.post_disbursement(text, text, text, text, numeric, int, date, date, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.post_schedule(text, int, jsonb, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.post_repayment(text, text, text, text, numeric, date, date, jsonb, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.reverse_repayment(text, text, text, text, text, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.set_officer_reference(text, text, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.set_purpose_plan(text, jsonb, text) OWNER TO edify_loans_ledger_owner;
ALTER FUNCTION gateway_loans_ledger.record_enrolment_baseline(text, int, date, text, text, text) OWNER TO edify_loans_ledger_owner;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_loans_ledger FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA gateway_loans_ledger TO edify_gateway;
