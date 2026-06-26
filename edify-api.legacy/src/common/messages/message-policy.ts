import { EdifyRole } from '@prisma/client';
import type { ContextType } from '../notifications/context-route';

// ── Role-specific message context policy (spec §5, §6, §7) ──────────────────
//
// Messages are intentional human-to-human communication. The product rule is
// that a message can NEVER be sent without a context, and the set of contexts a
// sender may pick is a function of (senderRole, recipientRole). A CD messaging a
// CCEO sees performance / school-coverage / fund-clarification contexts; a
// Partner messaging an Accountant only sees payment contexts. This module is the
// single source of truth the composer reads (allowed recipients + allowed
// contexts) and the send path enforces (reject anything off-matrix).
//
// It is intentionally pure data + pure functions: no DB, no Nest — so it can be
// exhaustively unit-tested (spec §20) and seeded into MessageContextPolicy rows.

/** The communication-facing role taxonomy used by the matrix. Maps many-to-one
 *  from the Prisma EdifyRole enum (e.g. both partner roles → 'Partner'). */
export type CommsRole = 'CD' | 'PL' | 'CCEO' | 'IA' | 'Accountant' | 'Partner' | 'RVP' | 'HR';

/** A single allowed message context for a (sender → recipient) pairing. */
export type MessageContextDef = {
  /** Stable slug stored on the message + thread (contextType discriminator). */
  key: string;
  /** Human label rendered in the composer + the message card context chip. */
  label: string;
  /** Whether the sender must attach a linked record before the message can send.
   *  Operational contexts (a specific school, fund request, evidence item) require
   *  one; relational contexts (encouragement, FY-end priority) do not. */
  requiresLinkedRecord: boolean;
  /** The record types a linked record may be — drives the record picker + the
   *  recipient-facing deep link (resolveContextRoute). Empty for record-less ones. */
  recordTypes: ContextType[];
};

const c = (
  key: string,
  label: string,
  requiresLinkedRecord: boolean,
  recordTypes: ContextType[] = [],
): MessageContextDef => ({ key, label, requiresLinkedRecord, recordTypes });

// Re-usable context groups so the same operational context keeps one slug/label
// across every role-pair that can raise it (a "fund-request-clarification" means
// the same thing whether CD→CCEO or PL→CD).
const FUND_CLARIFY = c('fund-request-clarification', 'Budget / fund request clarification', false, ['fund_request']);
const SCHOOL_IMPROVEMENT = c('school-improvement-concern', 'School improvement concern', true, ['school']);
const PARTNER_MONITORING = c('partner-monitoring', 'Partner monitoring issue', false, ['partner_assignment', 'partner_mou']);
const ENCOURAGEMENT = c('encouragement', 'Encouragement / appreciation', false, ['activity', 'school']);
const FYEND_FOLLOWUP = c('fy-end-priority', 'FY-end priority follow-up', false, []);
const EVIDENCE_CORRECTION = c('evidence-correction', 'Evidence / Activity Code correction', true, ['evidence', 'salesforce_verification']);
const SSA_DATA = c('ssa-data-quality', 'SSA data quality', true, ['data_quality_issue', 'school']);
const ACTIVITY_CODE = c('activity-code-verification', 'Salesforce / Activity Code verification', true, ['salesforce_verification', 'activity']);

// ── The matrix (spec §6) ────────────────────────────────────────────────────
// MATRIX[sender][recipient] = the exact contexts that pairing may use.
export const MESSAGE_CONTEXT_MATRIX: {
  [sender in CommsRole]?: { [recipient in CommsRole]?: MessageContextDef[] };
} = {
  // A. CD messaging contexts
  CD: {
    CCEO: [
      c('performance-progress', 'Performance and target progress', false, ['target_alert', 'staff_performance']),
      c('schools-lacking-activities', 'Schools lacking activities', false, ['school', 'planning_gap']),
      c('schools-not-visited', 'Schools not visited', false, ['school']),
      c('schools-not-trained', 'Schools not trained', false, ['school']),
      c('schools-without-ssa', 'Schools without SSA', false, ['school', 'data_quality_issue']),
      c('planning-gaps', 'Planning gaps', false, ['planning_gap']),
      FUND_CLARIFY,
      c('field-execution-issue', 'Field execution issue', false, ['activity']),
      ENCOURAGEMENT,
      SCHOOL_IMPROVEMENT,
      PARTNER_MONITORING,
      FYEND_FOLLOWUP,
    ],
    PL: [
      c('team-performance', 'Team performance', false, ['staff_performance', 'target_alert']),
      c('cceo-supervision', 'CCEO supervision', false, ['staff_performance']),
      c('planning-approval', 'Planning approval', false, ['planning_gap', 'my_plan_activity']),
      c('budget-fund-review', 'Budget and fund request review', false, ['fund_request']),
      c('cluster-performance', 'Cluster performance', false, ['cluster']),
      c('school-coverage-gaps', 'School coverage gaps', false, ['school', 'planning_gap']),
      c('partner-execution', 'Partner execution', false, ['partner_assignment']),
      c('ssa-completion', 'SSA completion', false, ['school', 'data_quality_issue']),
      c('district-region-bottleneck', 'District/region bottlenecks', false, ['risk_alert']),
      c('fy-end-delivery-risk', 'FY-end delivery risk', false, ['risk_alert']),
    ],
    IA: [
      SSA_DATA,
      c('school-upload-quality', 'School upload quality', false, ['data_quality_issue']),
      c('duplicate-school-review', 'Duplicate school review', false, ['data_quality_issue', 'school']),
      ACTIVITY_CODE,
      c('evidence-verification', 'Evidence verification', false, ['evidence', 'verification']),
      c('donor-ready-data', 'Donor-ready data', false, ['data_quality_issue']),
      c('missing-enrollment-geo', 'Missing enrollment/geography', true, ['data_quality_issue', 'school']),
      c('analytics-accuracy', 'Analytics/reporting accuracy', false, ['data_quality_issue']),
    ],
    Accountant: [
      c('fund-request-status', 'Fund request status', false, ['fund_request']),
      c('disbursement', 'Disbursement', false, ['payment', 'fund_request']),
      c('partner-payment', 'Partner payment', false, ['payment']),
      c('staff-accountability', 'Staff accountability', false, ['accountability']),
      c('budget-variance', 'Budget variance', false, ['fund_request']),
      c('cost-catalogue-issue', 'Cost catalogue issue', false, ['cost_catalogue']),
      c('netsuite-accountability', 'Netsuite accountability', false, ['accountability']),
      c('payment-blocker', 'Payment blocker', false, ['payment']),
    ],
    RVP: [
      c('country-budget-approval', 'Country budget approval', false, ['fund_request']),
      c('country-performance-summary', 'Country performance summary', false, ['target_alert']),
      c('strategic-risk', 'Strategic risk', false, ['risk_alert']),
      c('donor-ready-impact', 'Donor-ready impact', false, ['risk_alert']),
      c('fy-end-progress', 'FY-end progress', false, []),
      c('budget-variance', 'Budget variance', false, ['fund_request']),
      c('region-district-bottleneck', 'Region/district bottleneck', false, ['risk_alert']),
    ],
    HR: [
      c('staff-support', 'Staff support / wellbeing', false, ['staff_performance']),
      c('supervisor-assignment', 'Supervisor assignment', false, ['staff_performance']),
    ],
  },

  // B. PL messaging contexts
  PL: {
    CCEO: [
      c('target-progress', 'Target progress', false, ['target_alert', 'staff_performance']),
      c('plan-cycle', 'Monthly/weekly plan', false, ['my_plan_activity', 'planning_gap']),
      c('schools-lacking-visits', 'Schools lacking visits', false, ['school']),
      c('schools-lacking-training', 'Schools lacking training', false, ['school']),
      c('schools-without-ssa', 'Schools without SSA', false, ['school', 'data_quality_issue']),
      c('core-package-progress', 'Core school package progress', false, ['school']),
      c('cluster-meetings', 'Cluster meetings', false, ['cluster']),
      c('evidence-returned', 'Evidence returned', true, ['evidence']),
      c('activity-code-correction', 'Activity Code correction', true, ['salesforce_verification', 'activity']),
      c('field-support', 'Field support', false, ['activity']),
      ENCOURAGEMENT,
      c('rescheduling-pattern', 'Rescheduling pattern', false, ['activity']),
      PARTNER_MONITORING,
    ],
    CD: [
      c('team-progress', 'Team progress', false, ['staff_performance', 'target_alert']),
      c('field-constraints', 'Field constraints', false, ['risk_alert']),
      c('fund-request-issue', 'Fund request issue', false, ['fund_request']),
      c('budget-gap', 'Budget gap', false, ['fund_request']),
      c('partner-problem', 'Partner problem', false, ['partner_assignment']),
      c('cluster-challenge', 'Cluster challenge', false, ['cluster']),
      SCHOOL_IMPROVEMENT,
      c('staff-support-need', 'Staff support need', false, ['staff_performance']),
      c('fy-target-risk', 'FY target risk', false, ['risk_alert']),
    ],
    IA: [
      c('ssa-verification', 'SSA verification', true, ['data_quality_issue', 'school']),
      EVIDENCE_CORRECTION,
      c('activity-code-issue', 'Activity Code issue', true, ['salesforce_verification', 'activity']),
      c('school-data-mismatch', 'School data mismatch', true, ['data_quality_issue', 'school']),
      c('cluster-data-issue', 'Cluster data issue', false, ['cluster', 'data_quality_issue']),
      c('project-data-verification', 'Project data verification', false, ['special_project', 'data_quality_issue']),
    ],
    Accountant: [
      c('team-fund-request', 'Team fund request', false, ['fund_request']),
      c('staff-accountability', 'Staff accountability', false, ['accountability']),
      c('partner-payment-readiness', 'Partner payment readiness', false, ['payment']),
      c('reimbursement-issue', 'Reimbursement issue', false, ['payment']),
      c('budget-correction', 'Budget correction', false, ['fund_request']),
    ],
    Partner: [
      c('assigned-activity', 'Assigned activity', true, ['partner_assignment', 'activity']),
      c('partner-schedule', 'Partner schedule', true, ['partner_assignment']),
      EVIDENCE_CORRECTION,
      c('school-follow-up', 'School follow-up', true, ['school']),
      c('cluster-support', 'Cluster support', false, ['cluster']),
      c('project-support', 'Project support', false, ['special_project']),
      c('payment-status-clarification', 'Payment status clarification', false, ['payment']),
    ],
  },

  // C. CCEO messaging contexts
  CCEO: {
    PL: [
      c('planning-approval', 'Planning approval', false, ['planning_gap', 'my_plan_activity']),
      c('target-progress', 'Target progress', false, ['target_alert']),
      c('field-issue', 'Field issue', false, ['activity']),
      c('school-leader-unavailable', 'School leader unavailable', true, ['school']),
      c('rescheduling-reason', 'Rescheduling reason', true, ['activity']),
      c('partner-support-need', 'Partner support need', false, ['partner_assignment']),
      c('cluster-issue', 'Cluster issue', false, ['cluster']),
      c('school-urgent-support', 'School requiring urgent support', true, ['school']),
      c('evidence-code-clarification', 'Evidence/Activity Code clarification', false, ['evidence', 'salesforce_verification']),
      c('fund-request-issue', 'Fund request issue', false, ['fund_request']),
    ],
    CD: [
      c('field-escalation', 'Field escalation', false, ['risk_alert']),
      c('performance-update', 'Performance update', false, ['target_alert']),
      c('major-school-issue', 'Major school issue', true, ['school']),
      c('district-constraint', 'District constraint', false, ['risk_alert']),
      c('partner-issue', 'Partner issue', false, ['partner_assignment']),
      FUND_CLARIFY,
      SCHOOL_IMPROVEMENT,
      c('appreciation-impact', 'Appreciation/impact story', false, ['school', 'activity']),
    ],
    IA: [
      SSA_DATA,
      c('school-data-correction', 'School data correction', true, ['data_quality_issue', 'school']),
      ACTIVITY_CODE,
      c('evidence-clarification', 'Evidence clarification', false, ['evidence']),
      c('duplicate-school-issue', 'Duplicate school issue', false, ['data_quality_issue', 'school']),
      c('enrollment-geo-correction', 'Enrollment/geography correction', true, ['data_quality_issue', 'school']),
    ],
    Accountant: [
      c('fund-disbursement', 'Fund disbursement', false, ['payment', 'fund_request']),
      c('accountability', 'Accountability', false, ['accountability']),
      c('reimbursement', 'Reimbursement', false, ['payment']),
      c('partner-payment-followup', 'Partner payment follow-up', false, ['payment']),
      c('netsuite-expense-id', 'Netsuite Expense ID issue', false, ['accountability']),
    ],
    Partner: [
      c('assigned-school-visit', 'Assigned school visit', true, ['partner_assignment', 'school']),
      c('partner-scheduling', 'Partner scheduling', true, ['partner_assignment']),
      EVIDENCE_CORRECTION,
      c('reschedule-reason', 'Reschedule reason', true, ['partner_assignment', 'activity']),
      c('school-follow-up', 'School follow-up', true, ['school']),
      c('project-support', 'Project support', false, ['special_project']),
    ],
  },

  // D. IA messaging contexts
  IA: {
    CCEO: [
      c('ssa-missing', 'SSA missing', true, ['school', 'data_quality_issue']),
      c('ssa-upload-issue', 'SSA upload issue', true, ['data_quality_issue']),
      c('evidence-issue', 'Evidence issue', true, ['evidence']),
      c('activity-code-correction', 'Activity Code correction', true, ['salesforce_verification', 'activity']),
      ACTIVITY_CODE,
      c('duplicate-school-issue', 'Duplicate school issue', false, ['data_quality_issue', 'school']),
      c('school-data-quality', 'School data quality', false, ['data_quality_issue', 'school']),
      c('enrollment-missing', 'Enrollment missing', true, ['data_quality_issue', 'school']),
      c('geography-missing', 'Geography missing', true, ['data_quality_issue', 'school']),
    ],
    PL: [
      c('ssa-missing', 'SSA missing', true, ['school', 'data_quality_issue']),
      c('ssa-upload-issue', 'SSA upload issue', true, ['data_quality_issue']),
      c('evidence-issue', 'Evidence issue', true, ['evidence']),
      c('activity-code-correction', 'Activity Code correction', true, ['salesforce_verification', 'activity']),
      ACTIVITY_CODE,
      c('duplicate-school-issue', 'Duplicate school issue', false, ['data_quality_issue', 'school']),
      c('school-data-quality', 'School data quality', false, ['data_quality_issue', 'school']),
      c('enrollment-missing', 'Enrollment missing', true, ['data_quality_issue', 'school']),
      c('geography-missing', 'Geography missing', true, ['data_quality_issue', 'school']),
    ],
    CD: [
      c('data-quality-blocker', 'Data quality blocker', false, ['data_quality_issue']),
      c('ssa-coverage-risk', 'SSA coverage risk', false, ['risk_alert', 'data_quality_issue']),
      c('donor-ready-data-issue', 'Donor-ready data issue', false, ['data_quality_issue']),
      c('upload-errors', 'Upload errors', false, ['data_quality_issue']),
      c('duplicate-school-risk', 'Duplicate school risk', false, ['data_quality_issue']),
      c('verification-bottleneck', 'Verification bottleneck', false, ['verification']),
    ],
    Accountant: [
      c('ia-confirmed-activity', 'IA confirmed activity', true, ['salesforce_verification', 'activity']),
      c('activity-returned', 'Activity returned', true, ['salesforce_verification', 'activity']),
      c('payment-not-ready', 'Payment not ready', true, ['payment', 'activity']),
      c('evidence-mismatch', 'Evidence mismatch', true, ['evidence']),
      c('verification-issue', 'Verification issue', false, ['verification']),
    ],
  },

  // E. Accountant messaging contexts
  Accountant: {
    CCEO: [
      c('fund-request-correction', 'Fund request correction', true, ['fund_request']),
      c('disbursement-status', 'Disbursement status', false, ['payment', 'fund_request']),
      c('accountability-pending', 'Accountability pending', false, ['accountability']),
      c('netsuite-expense-id', 'Netsuite Expense ID', false, ['accountability']),
      c('reimbursement-issue', 'Reimbursement issue', false, ['payment']),
      c('partner-payment-blocker', 'Partner payment blocker', false, ['payment']),
    ],
    PL: [
      c('fund-request-correction', 'Fund request correction', true, ['fund_request']),
      c('disbursement-status', 'Disbursement status', false, ['payment', 'fund_request']),
      c('accountability-pending', 'Accountability pending', false, ['accountability']),
      c('netsuite-expense-id', 'Netsuite Expense ID', false, ['accountability']),
      c('reimbursement-issue', 'Reimbursement issue', false, ['payment']),
      c('partner-payment-blocker', 'Partner payment blocker', false, ['payment']),
    ],
    CD: [
      c('budget-issue', 'Budget issue', false, ['fund_request']),
      c('fund-request-approval', 'Fund request approval', false, ['fund_request']),
      c('cost-catalogue-issue', 'Cost catalogue issue', false, ['cost_catalogue']),
      c('payment-risk', 'Payment risk', false, ['payment']),
      c('cash-flow-need', 'Cash flow need', false, ['fund_request']),
      c('accountability-backlog', 'Accountability backlog', false, ['accountability']),
    ],
    Partner: [
      c('payment-status', 'Payment status', false, ['payment']),
      c('missing-payment-requirement', 'Missing payment requirement', true, ['payment']),
      c('returned-payment-proof', 'Returned payment proof', true, ['payment']),
      c('payment-cleared', 'Payment cleared', true, ['payment']),
    ],
  },

  // F. Partner messaging contexts
  Partner: {
    CCEO: [
      c('assigned-school-visit', 'Assigned school visit', true, ['partner_assignment', 'school']),
      c('schedule-confirmation', 'Schedule confirmation', true, ['partner_assignment']),
      c('reschedule-request', 'Reschedule request', true, ['partner_assignment', 'activity']),
      c('evidence-submission-issue', 'Evidence submission issue', true, ['evidence']),
      c('school-leader-unavailable', 'School leader unavailable', true, ['school']),
      c('field-constraint', 'Field constraint', false, ['activity']),
      c('payment-follow-up', 'Payment follow-up', false, ['payment']),
    ],
    PL: [
      c('assigned-school-visit', 'Assigned school visit', true, ['partner_assignment', 'school']),
      c('schedule-confirmation', 'Schedule confirmation', true, ['partner_assignment']),
      c('reschedule-request', 'Reschedule request', true, ['partner_assignment', 'activity']),
      c('evidence-submission-issue', 'Evidence submission issue', true, ['evidence']),
      c('school-leader-unavailable', 'School leader unavailable', true, ['school']),
      c('field-constraint', 'Field constraint', false, ['activity']),
      c('payment-follow-up', 'Payment follow-up', false, ['payment']),
    ],
    Accountant: [
      c('payment-status', 'Payment status', false, ['payment']),
      c('payment-clarification', 'Payment clarification', false, ['payment']),
    ],
  },

  // G. HR messaging contexts (HR → Staff). Modelled per supervised role.
  HR: {
    CCEO: hrStaffContexts(),
    PL: hrStaffContexts(),
    IA: hrStaffContexts(),
    Accountant: hrStaffContexts(),
    CD: hrStaffContexts(),
  },

  // RVP messaging contexts (spec §7: RVP can message CD, PL, IA, Accountant, HR;
  // not partners by default). Mirrors the CD↔leadership operating contexts.
  RVP: {
    CD: [
      c('country-budget-approval', 'Country budget approval', false, ['fund_request']),
      c('country-performance-summary', 'Country performance summary', false, ['target_alert']),
      c('strategic-risk', 'Strategic risk', false, ['risk_alert']),
      c('fy-end-progress', 'FY-end progress', false, []),
      c('region-district-bottleneck', 'Region/district bottleneck', false, ['risk_alert']),
    ],
    PL: [
      c('country-performance-summary', 'Country performance summary', false, ['target_alert']),
      c('fy-end-progress', 'FY-end progress', false, []),
      c('region-district-bottleneck', 'Region/district bottleneck', false, ['risk_alert']),
    ],
    IA: [
      c('donor-ready-data-issue', 'Donor-ready data issue', false, ['data_quality_issue']),
      c('ssa-coverage-risk', 'SSA coverage risk', false, ['risk_alert']),
    ],
    Accountant: [
      c('country-budget-approval', 'Country budget approval', false, ['fund_request']),
      c('budget-variance', 'Budget variance', false, ['fund_request']),
    ],
    HR: [c('staff-support', 'Staff support / wellbeing', false, ['staff_performance'])],
  },
};

function hrStaffContexts(): MessageContextDef[] {
  return [
    c('workload-support', 'Workload support', false, ['staff_performance']),
    c('reschedule-patterns', 'Reschedule patterns', false, ['staff_performance']),
    c('leave', 'Leave', false, ['leave_request']),
    c('debrief-follow-up', 'Debrief follow-up', false, ['daily_debrief']),
    c('staff-wellbeing', 'Staff wellbeing', false, ['staff_performance']),
    c('performance-support', 'Performance support', false, ['staff_performance']),
    c('onboarding', 'Onboarding', false, ['staff_performance']),
    c('supervisor-assignment', 'Supervisor assignment', false, ['staff_performance']),
  ];
}

// ── EdifyRole → CommsRole mapping ───────────────────────────────────────────
export function commsRoleFor(role: EdifyRole): CommsRole | null {
  switch (role) {
    case 'CountryDirector':
      return 'CD';
    case 'CountryProgramLead':
      return 'PL';
    case 'CCEO':
      return 'CCEO';
    case 'ImpactAssessment':
      return 'IA';
    case 'ProgramAccountant':
      return 'Accountant';
    case 'PartnerAdmin':
    case 'PartnerFieldOfficer':
      return 'Partner';
    case 'RegionalVicePresident':
      return 'RVP';
    case 'HumanResources':
      return 'HR';
    // ProjectCoordinator + Admin have no dedicated matrix; Admin is allowed
    // anything by the caller, ProjectCoordinator falls back to no contexts.
    default:
      return null;
  }
}

// ── Public policy queries (composer + send-path enforcement) ────────────────

/** The recipient roles a sender may address (spec §7). Derived from the matrix
 *  so it can never drift from the contexts that actually exist for the pairing. */
export function allowedRecipientCommsRoles(sender: CommsRole): CommsRole[] {
  return Object.keys(MESSAGE_CONTEXT_MATRIX[sender] ?? {}) as CommsRole[];
}

/** All EdifyRoles a given sender role may message. Admin can reach everyone. */
export function allowedRecipientRoles(senderRole: EdifyRole): EdifyRole[] {
  if (senderRole === 'Admin') return ALL_ROLES;
  const sender = commsRoleFor(senderRole);
  if (!sender) return [];
  const recipientComms = new Set(allowedRecipientCommsRoles(sender));
  return ALL_ROLES.filter((r) => {
    const cr = commsRoleFor(r);
    return cr !== null && recipientComms.has(cr);
  });
}

/** The allowed contexts for a (sender → recipient) pairing. Empty array means
 *  the sender may NOT message that recipient (off-matrix). */
export function allowedContexts(senderRole: EdifyRole, recipientRole: EdifyRole): MessageContextDef[] {
  const sender = commsRoleFor(senderRole);
  const recipient = commsRoleFor(recipientRole);
  if (senderRole === 'Admin') {
    // Admin oversight: union of every context defined for the recipient role so
    // an admin can still raise any operational topic. Dedup by key.
    const seen = new Map<string, MessageContextDef>();
    for (const s of Object.keys(MESSAGE_CONTEXT_MATRIX) as CommsRole[]) {
      for (const def of MESSAGE_CONTEXT_MATRIX[s]?.[recipient ?? ('CD' as CommsRole)] ?? []) {
        if (!seen.has(def.key)) seen.set(def.key, def);
      }
    }
    return [...seen.values()];
  }
  if (!sender || !recipient) return [];
  return MESSAGE_CONTEXT_MATRIX[sender]?.[recipient] ?? [];
}

/** Whether a sender may message a recipient at all (spec §7 recipient filtering). */
export function canMessageRole(senderRole: EdifyRole, recipientRole: EdifyRole): boolean {
  if (senderRole === 'Admin') return true;
  return allowedRecipientRoles(senderRole).includes(recipientRole);
}

/** Resolve a context definition for a (sender → recipient, key). Returns null
 *  when the key is not allowed for that pairing — the send-path rejects on null. */
export function resolveContext(
  senderRole: EdifyRole,
  recipientRole: EdifyRole,
  contextKey: string,
): MessageContextDef | null {
  return allowedContexts(senderRole, recipientRole).find((d) => d.key === contextKey) ?? null;
}

/** A single validation result for the send path (spec §5 + §19 health checks). */
export type MessagePolicyCheck =
  | { ok: true; context: MessageContextDef }
  | { ok: false; reason: string };

/** Enforce the full message policy: recipient in scope, context selected,
 *  context allowed for the pairing, and a linked record present when required. */
export function checkMessagePolicy(input: {
  senderRole: EdifyRole;
  recipientRole: EdifyRole;
  contextKey?: string | null;
  contextId?: string | null;
}): MessagePolicyCheck {
  if (!canMessageRole(input.senderRole, input.recipientRole)) {
    return { ok: false, reason: `A ${input.senderRole} may not message a ${input.recipientRole}.` };
  }
  if (!input.contextKey?.trim()) {
    return { ok: false, reason: 'A context is required for every message.' };
  }
  const def = resolveContext(input.senderRole, input.recipientRole, input.contextKey.trim());
  if (!def) {
    return { ok: false, reason: `"${input.contextKey}" is not an allowed context for ${input.senderRole} → ${input.recipientRole}.` };
  }
  if (def.requiresLinkedRecord && !input.contextId?.trim()) {
    return { ok: false, reason: `The "${def.label}" context requires a linked record.` };
  }
  return { ok: true, context: def };
}

const ALL_ROLES: EdifyRole[] = [
  'CCEO',
  'CountryProgramLead',
  'CountryDirector',
  'RegionalVicePresident',
  'ImpactAssessment',
  'ProgramAccountant',
  'HumanResources',
  'ProjectCoordinator',
  'PartnerAdmin',
  'PartnerFieldOfficer',
  'Admin',
];
