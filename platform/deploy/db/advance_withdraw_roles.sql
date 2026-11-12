-- The third Go save, cancelling a school visit (docs/migration/30), withdraws
-- the visit's advances whose money has not moved, inside its own transaction,
-- as the existing cancel does (apps.activities.services._cancel_or_defer:
-- AdvanceRequest.objects.filter(activity=a).exclude(
-- status__in=MONEY_MOVED_ADVANCE_STATUSES).delete()). The owner chose a narrow
-- function for it (30 §30.4, 03 §3.7, 2026-11-12): the gateway holds no
-- DELETE anywhere, and may only ask this function, which removes exactly
-- those rows of one activity and nothing else.
--
-- The function's owner is a NOLOGIN role nobody is a member of, holding only
-- DELETE on advance_request and the SELECT its filter reads. The statuses are
-- MONEY_MOVED_ADVANCE_STATUSES (apps/fund_requests/models.py), exported to
-- platform/backend/internal/activities/rules.json (cancel.money_moved_advance_statuses);
-- TestTheWithdrawFunctionNamesTheMovedStatuses fails when they differ.
--
-- Applied after activities_roles.sql (apply-roles.sh, the integration TestMain).
-- Idempotent. A new database object: production needs the owner's approval
-- at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_advance_withdraw_owner') THEN
    CREATE ROLE edify_advance_withdraw_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_advance_withdraw_owner;
GRANT USAGE ON SCHEMA public TO edify_advance_withdraw_owner;
GRANT SELECT (activity_id, status) ON advance_request TO edify_advance_withdraw_owner;
GRANT DELETE ON advance_request TO edify_advance_withdraw_owner;

CREATE SCHEMA IF NOT EXISTS gateway_money AUTHORIZATION edify_advance_withdraw_owner;
REVOKE ALL ON SCHEMA gateway_money FROM PUBLIC;

SET ROLE edify_advance_withdraw_owner;
CREATE OR REPLACE FUNCTION gateway_money.withdraw_unmoved_advances(target_activity varchar) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  removed integer;
BEGIN
  DELETE FROM public.advance_request r
  WHERE r.activity_id = target_activity
    AND NOT (r.status = ANY (ARRAY[
      'disbursed', 'accountability_pl_pending', 'accountability_pending', 'accounted',
      'reimbursement_pl_pending', 'reimbursement_submitted', 'reimbursement_disbursed', 'reimbursed'
    ]::varchar[]));
  GET DIAGNOSTICS removed = ROW_COUNT;
  RETURN removed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_money.withdraw_unmoved_advances(varchar) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_money TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_money.withdraw_unmoved_advances(varchar) TO edify_activities_rw;
