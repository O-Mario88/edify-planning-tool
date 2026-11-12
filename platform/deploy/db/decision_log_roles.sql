-- The Decision Log's window on the audit chain. Applied by apply-roles.sh to a
-- development, test or staging database; never to production without the
-- owner's approval at cutover.
--
-- The gateway may not read audit_log.payload: the chain records sign-ins,
-- invitations, resets and every other piece of machinery, and their payloads
-- are not the gateway's to read (TestGatewayRoleCanNeitherWriteNorReadSecrets).
-- The Decision Log (apps.audit.decision_log_service) needs only the decision
-- rows, and of their payloads only the keys a row's subject is read from
-- (DETAIL_KEYS) and "decision". This view shows exactly that, and the gateway
-- reads the view, never the table.
--
-- Nothing here touches a table, column, index, constraint or row of the
-- existing schema. The view lives in its own schema, gateway_read, owned by
-- edify_audit_view_owner: a NOLOGIN role no one is a member of, holding
-- SELECT on the audit columns the view shows and nothing else.
--
-- The two lists below are the exported rules (internal/decisionlog/rules.json,
-- drift-tested against the Python), and TestTheDecisionLogViewShowsOnlyDecisions
-- fails when they part.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_audit_view_owner') THEN
    CREATE ROLE edify_audit_view_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_audit_view_owner;
GRANT USAGE ON SCHEMA public TO edify_audit_view_owner;
GRANT SELECT (id, action, actor_id, actor_role, subject_id, payload, success, reason, created_at)
  ON audit_log TO edify_audit_view_owner;

CREATE SCHEMA IF NOT EXISTS gateway_read AUTHORIZATION edify_audit_view_owner;
REVOKE ALL ON SCHEMA gateway_read FROM PUBLIC;

-- Built as the owner, so the view reads with the owner's privileges only.
SET ROLE edify_audit_view_owner;
CREATE OR REPLACE VIEW gateway_read.decision_audit AS
SELECT a.id, a.action, a.actor_id, a.actor_role, a.subject_id, a.success, a.reason, a.created_at,
  CASE WHEN jsonb_typeof(a.payload) = 'object' THEN (
    SELECT COALESCE(jsonb_object_agg(e.key, e.value), '{}'::jsonb)
    FROM jsonb_each(a.payload) AS e
    WHERE e.key = ANY (ARRAY[
        'staffName',
        'schoolName',
        'projectName',
        'name',
        'subject',
        'course',
        'monthKey',
        'decision'
      ]::text[])
  ) END AS payload
FROM public.audit_log a
WHERE a.action = ANY (ARRAY[
    'country_budget_approved_by_rvp',
    'country_budget_returned_by_rvp',
    'country_budget_submitted_to_rvp',
    'country_budget_sent_to_accountant',
    'country_budget_disbursed',
    'country_budget_closed',
    'rvp_annual_approve',
    'rvp_annual_return',
    'finance_partner_payment_clear',
    'accountability_submitted',
    'pd_supervisor_approve',
    'pd_supervisor_return',
    'pd_hr_approve',
    'pd_hr_return',
    'pd_hr_reject',
    'leave.approved',
    'leave.rejected',
    'hr.coverage_granted',
    'hr.coverage_reassigned',
    'hr.coverage_revoked',
    'project_create',
    'special_project',
    'strategy_note',
    'plan_approve',
    'plan_return',
    'school.assign_project',
    'school.bulk_assign_project',
    'ssa_verify',
    'ssa_return',
    'ia_verify_completion',
    'ia_return_completion',
    'pl_approve_completion',
    'pl_return_completion',
    'flag_acknowledge',
    'flag_resolve',
    'escalation_raise',
    'escalation_acknowledge',
    'escalation_resolve',
    'ia.report.submitted',
    'ia.report.reviewed',
    'ia.report.returned',
    'ia.report.released',
    'ia.report.donor_requested',
    'ia.report.donor_released',
    'ia.report.donor_declined',
    'ia.report.recommendation_responded',
    'ia.report.school_brief_shared',
    'ia.report.correction_started',
    'ia.report.superseded'
  ]::text[]);
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_read TO edify_gateway_ro;
GRANT SELECT ON gateway_read.decision_audit TO edify_gateway_ro;
