import { EdifyRole } from '@prisma/client';
import type { ContextType } from './context-route';

// ── Notification rule engine (spec §9, §10, §14, §15) ───────────────────────
//
// Notifications are SYSTEM-generated workflow events — never decorative, always
// carrying a target route + action. Every workflow emits a domain event; this
// engine is the single declarative table that turns an event type into:
//   • a priority (spec §14)
//   • a title + body template
//   • the context type that drives the recipient-role deep link
//   • the AUDIENCE (which roles should be notified — spec §15)
//   • whether the notification requires action
//
// It is pure data + pure functions so it can be exhaustively unit-tested (§20)
// and so DomainEventService callers can resolve "who + what + where" from one
// source of truth instead of hand-writing NotifySpecs at every call site.

/** DB-stored priority. */
export type NotificationPriority = 'low' | 'normal' | 'high' | 'urgent';
/** Spec §14 priority vocabulary (richer than the DB enum; mapped via dbPriority). */
export type SpecPriority = 'low' | 'normal' | 'medium' | 'high' | 'urgent' | 'critical';

/** Audience targets a rule resolves to. `actor`/`submitter`/`assignee`/etc. are
 *  resolved by the caller (it knows the concrete user ids for the aggregate);
 *  role targets are expanded to every user holding that role. */
export type AudienceTarget =
  | { kind: 'role'; role: EdifyRole; summaryOnly?: boolean }
  | { kind: 'assignee' }
  | { kind: 'submitter' }
  | { kind: 'supervisor' }
  | { kind: 'account_owner' }
  | { kind: 'next_approver' }
  | { kind: 'corrector' };

export type NotificationRule = {
  /** Workflow domain event this rule fires for (spec §9 event catalogue). */
  event: string;
  priority: SpecPriority;
  contextType: ContextType;
  actionRequired: boolean;
  title: string;
  /** Body template — `{name}` / `{detail}` interpolated by render(). */
  body: string;
  audience: AudienceTarget[];
};

// ── Action label (spec §16 actionLabel / §12 "action label") ─────────────────
// Every notification carries a verb the recipient acts on. Derived from the
// rule's context + whether action is required, so the rail can render a CTA
// ("Review", "Pay", "Correct", "Open") without hand-writing one per rule.
const ACTION_LABEL_BY_CONTEXT: Partial<Record<ContextType, string>> = {
  evidence: 'Review evidence',
  verification: 'Verify',
  salesforce_verification: 'Verify',
  payment: 'Process payment',
  accountability: 'Review accountability',
  fund_request: 'Review request',
  my_plan_activity: 'Open plan',
  activity: 'Open activity',
  partner_assignment: 'Open assignment',
  planning_gap: 'Plan support',
  school: 'Open school',
  data_quality_issue: 'Fix data',
  cluster: 'Open cluster',
  risk_alert: 'Review risk',
  target_alert: 'View targets',
  staff_performance: 'View staff',
};

export function actionLabelFor(rule: NotificationRule): string {
  if (!rule.actionRequired) return 'Open';
  return ACTION_LABEL_BY_CONTEXT[rule.contextType] ?? 'Open';
}

const r = (
  event: string,
  priority: SpecPriority,
  contextType: ContextType,
  actionRequired: boolean,
  title: string,
  body: string,
  audience: AudienceTarget[],
): NotificationRule => ({ event, priority, contextType, actionRequired, title, body, audience });

const role = (role: EdifyRole, summaryOnly = false): AudienceTarget => ({ kind: 'role', role, summaryOnly });

// ── The rule table ──────────────────────────────────────────────────────────
export const NOTIFICATION_RULES: NotificationRule[] = [
  // A. Activity timing (spec §10.A)
  r('ActivityPlanned', 'medium', 'my_plan_activity', false, 'Activity planned', '{name}: {detail}', [{ kind: 'assignee' }]),
  r('ActivityAssignedToPartner', 'high', 'partner_assignment', true, 'New activity assigned to you', '{detail}', [{ kind: 'assignee' }]),
  r('PartnerScheduledActivity', 'normal', 'activity', false, 'Partner scheduled an activity', '{name}: {detail}', [{ kind: 'assignee' }, role('CountryProgramLead', true)]),
  r('ActivityDueSoon', 'medium', 'my_plan_activity', true, 'Activity due soon', '{detail}', [{ kind: 'assignee' }]),
  r('ActivityDueToday', 'high', 'my_plan_activity', true, 'Activity due today', '{detail}', [{ kind: 'assignee' }]),
  r('ActivityPastDue', 'urgent', 'my_plan_activity', true, 'Activity past due', '{detail}', [{ kind: 'assignee' }, { kind: 'supervisor' }]),
  r('ActivityRescheduled', 'normal', 'activity', false, 'Activity rescheduled', '{detail}', [{ kind: 'assignee' }, { kind: 'supervisor' }]),
  r('ActivityCompleted', 'normal', 'activity', false, 'Activity completed', '{name}: {detail}', [{ kind: 'supervisor' }]),

  // B. Evidence (spec §10.B)
  r('EvidenceUploaded', 'normal', 'evidence', true, 'Evidence uploaded for review', '{name}: {detail}', [{ kind: 'supervisor' }]),
  r('EvidenceReturned', 'high', 'evidence', true, 'Evidence returned for correction', '{detail}', [{ kind: 'corrector' }]),
  r('EvidenceAccepted', 'low', 'evidence', false, 'Evidence accepted', '{detail}', [{ kind: 'assignee' }]),
  r('EvidenceMissing', 'high', 'evidence', true, 'Evidence missing after completion', '{detail}', [{ kind: 'assignee' }, { kind: 'supervisor' }]),

  // Activity code / verification handoffs (spec §9 + §15)
  r('ActivityCodeSubmitted', 'normal', 'salesforce_verification', true, 'Activity Code submitted', '{detail}', [role('ImpactAssessment')]),
  r('SubmittedToPL', 'high', 'verification', true, 'Completion submitted for PL review', '{name}: {detail}', [{ kind: 'supervisor' }, role('CountryProgramLead', true)]),
  r('PLReturnedActivity', 'high', 'verification', true, 'Activity returned by PL', '{detail}', [{ kind: 'corrector' }]),
  r('PLConfirmedActivity', 'normal', 'verification', true, 'Activity confirmed by PL', '{detail}', [role('ImpactAssessment')]),
  r('SubmittedToIA', 'high', 'verification', true, 'Activity awaiting IA verification', '{detail}', [role('ImpactAssessment')]),
  r('IAReturnedActivity', 'high', 'salesforce_verification', true, 'Activity returned by IA', '{detail}', [{ kind: 'corrector' }]),
  r('IAConfirmedActivity', 'high', 'payment', true, 'Activity verified — ready for payment', '{detail}', [role('ProgramAccountant'), { kind: 'submitter' }]),
  r('SentToAccountant', 'high', 'payment', true, 'Payment action pending', '{detail}', [role('ProgramAccountant')]),
  r('PaymentCleared', 'normal', 'payment', false, 'Payment cleared', '{detail}', [{ kind: 'assignee' }, { kind: 'supervisor' }]),
  r('AccountabilityCompleted', 'normal', 'accountability', false, 'Accountability completed', '{detail}', [{ kind: 'submitter' }, { kind: 'supervisor' }]),

  // Fund request routing (spec §11) — detailed routing lives in fund-requests
  // service; these provide the canonical priority/title/audience defaults.
  r('FundRequestSubmitted', 'high', 'fund_request', true, 'Fund request to review', '{name}: {detail}', [{ kind: 'next_approver' }]),
  r('FundRequestApprovedByPL', 'normal', 'fund_request', false, 'Fund request approved by PL', '{detail}', [{ kind: 'submitter' }, role('CountryDirector')]),
  r('FundRequestApprovedByCD', 'high', 'fund_request', true, 'Fund request approved by CD', '{detail}', [{ kind: 'submitter' }, role('RegionalVicePresident', true)]),
  r('FundRequestSubmittedToRVP', 'high', 'fund_request', true, 'Country fund request to approve', '{detail}', [role('RegionalVicePresident', true)]),
  r('FundRequestApprovedByRVP', 'high', 'fund_request', true, 'Country fund request approved', '{detail}', [role('CountryDirector'), role('ProgramAccountant')]),
  r('FundRequestReturned', 'high', 'fund_request', true, 'Fund request returned', '{detail}', [{ kind: 'submitter' }]),
  r('FundsDisbursed', 'normal', 'fund_request', false, 'Funds disbursed', '{detail}', [{ kind: 'submitter' }, { kind: 'supervisor' }]),

  // C. Planning gaps (spec §10.C)
  r('SchoolUploaded', 'low', 'school', false, 'School uploaded', '{detail}', [role('ImpactAssessment', true)]),
  r('SchoolUnclustered', 'medium', 'school', true, 'School is unclustered', '{detail}', [{ kind: 'account_owner' }, role('CountryProgramLead', true)]),
  r('SchoolClustered', 'low', 'cluster', false, 'School clustered', '{detail}', [{ kind: 'account_owner' }]),
  r('SSAMissing', 'critical', 'data_quality_issue', true, 'School without SSA', '{detail}', [{ kind: 'account_owner' }, role('CountryProgramLead'), role('ImpactAssessment'), role('CountryDirector', true)]),
  r('SSAUploaded', 'low', 'data_quality_issue', false, 'SSA uploaded', '{detail}', [{ kind: 'account_owner' }]),
  r('SchoolNotVisited', 'high', 'school', true, 'School not visited', '{detail}', [{ kind: 'account_owner' }, role('CountryProgramLead'), role('CountryDirector', true)]),
  r('SchoolNotTrained', 'high', 'school', true, 'School not trained', '{detail}', [{ kind: 'account_owner' }, role('CountryProgramLead'), role('CountryDirector', true)]),

  // D. School improvement (spec §10.D)
  r('PotentialCoreFlagged', 'medium', 'school', true, 'Potential core school flagged', '{detail}', [role('CCEO'), role('CountryProgramLead'), role('CountryDirector', true), role('ImpactAssessment')]),
  r('ChampionSchoolFlagged', 'low', 'school', false, 'Champion school flagged', '{detail}', [role('CCEO'), role('CountryProgramLead'), role('CountryDirector', true), role('RegionalVicePresident', true)]),
  r('StrugglingSchoolFlagged', 'medium', 'risk_alert', true, 'Struggling school detected', '{detail}', [{ kind: 'account_owner' }, role('CountryProgramLead'), role('CountryDirector', true)]),

  // E. FY-end (spec §10.E)
  r('FYEndRiskDetected', 'critical', 'risk_alert', true, 'FY-end risk detected', '{detail}', [role('CountryProgramLead'), role('CountryDirector'), role('RegionalVicePresident', true)]),
];

// `medium`/`critical` aren't in the DB NotificationPriority enum — they map to
// the nearest stored value while keeping the spec's §14 priority vocabulary in
// the rule table for clarity + tests.
const PRIORITY_TO_DB: Record<string, 'low' | 'normal' | 'high' | 'urgent'> = {
  low: 'low',
  normal: 'normal',
  medium: 'normal',
  high: 'high',
  urgent: 'urgent',
  critical: 'urgent',
};

export function dbPriority(p: string): 'low' | 'normal' | 'high' | 'urgent' {
  return PRIORITY_TO_DB[p] ?? 'normal';
}

const RULES_BY_EVENT = new Map(NOTIFICATION_RULES.map((rule) => [rule.event, rule]));

/** The rule for a workflow event, or null when the event has no notification
 *  rule (spec §19 health check: an emitted workflow event with no rule is a gap). */
export function ruleFor(event: string): NotificationRule | null {
  return RULES_BY_EVENT.get(event) ?? null;
}

/** Render a rule's title/body with the event's interpolation values. */
export function renderRule(rule: NotificationRule, vars: { name?: string; detail?: string }): { title: string; body: string } {
  const fill = (s: string) => s.replace('{name}', vars.name ?? '').replace('{detail}', vars.detail ?? '').replace(/^:\s*/, '').trim();
  return { title: fill(rule.title), body: fill(rule.body) };
}

export type ResolvedAudience = {
  /** Concrete user ids the caller supplies for relational targets. */
  assignee?: string | null;
  submitter?: string | null;
  supervisorIds?: string[];
  accountOwnerId?: string | null;
  nextApproverIds?: string[];
  correctorId?: string | null;
  /** role → userIds, supplied by the caller (DomainEventService.usersWithRole). */
  usersByRole?: Partial<Record<EdifyRole, string[]>>;
};

/**
 * Expand a rule's audience into the concrete recipient user ids, using the
 * relational ids + role rosters the caller resolved for this aggregate.
 * Deduped so the same person never gets two copies of one event.
 */
export function resolveRecipients(rule: NotificationRule, audience: ResolvedAudience): string[] {
  const out = new Set<string>();
  for (const t of rule.audience) {
    switch (t.kind) {
      case 'role':
        for (const id of audience.usersByRole?.[t.role] ?? []) out.add(id);
        break;
      case 'assignee':
        if (audience.assignee) out.add(audience.assignee);
        break;
      case 'submitter':
        if (audience.submitter) out.add(audience.submitter);
        break;
      case 'supervisor':
        for (const id of audience.supervisorIds ?? []) out.add(id);
        break;
      case 'account_owner':
        if (audience.accountOwnerId) out.add(audience.accountOwnerId);
        break;
      case 'next_approver':
        for (const id of audience.nextApproverIds ?? []) out.add(id);
        break;
      case 'corrector':
        if (audience.correctorId) out.add(audience.correctorId);
        break;
    }
  }
  return [...out];
}
