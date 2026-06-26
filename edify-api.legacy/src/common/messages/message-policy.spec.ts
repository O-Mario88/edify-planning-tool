import { describe, it, expect } from 'vitest';
import {
  allowedContexts,
  allowedRecipientRoles,
  canMessageRole,
  checkMessagePolicy,
  commsRoleFor,
  resolveContext,
} from './message-policy';

// Spec §20 — message context policy tests. These lock the role-specific matrix
// so the composer can never offer (or the send path accept) an off-policy
// context, and so a sender can never reach a recipient outside their scope.

const keys = (sender: Parameters<typeof allowedContexts>[0], recipient: Parameters<typeof allowedContexts>[1]) =>
  allowedContexts(sender, recipient).map((d) => d.key);

describe('commsRoleFor', () => {
  it('maps Prisma roles to the comms taxonomy', () => {
    expect(commsRoleFor('CountryDirector')).toBe('CD');
    expect(commsRoleFor('CountryProgramLead')).toBe('PL');
    expect(commsRoleFor('ImpactAssessment')).toBe('IA');
    expect(commsRoleFor('ProgramAccountant')).toBe('Accountant');
    expect(commsRoleFor('PartnerFieldOfficer')).toBe('Partner');
    expect(commsRoleFor('RegionalVicePresident')).toBe('RVP');
    expect(commsRoleFor('HumanResources')).toBe('HR');
  });
});

describe('CD messaging contexts', () => {
  it('CD → CCEO includes performance, schools lacking activities, not visited, fund clarification', () => {
    const k = keys('CountryDirector', 'CCEO');
    expect(k).toContain('performance-progress');
    expect(k).toContain('schools-lacking-activities');
    expect(k).toContain('schools-not-visited');
    expect(k).toContain('fund-request-clarification');
    expect(k).toContain('encouragement');
  });

  it('CD → IA includes SSA / data quality / verification', () => {
    const k = keys('CountryDirector', 'ImpactAssessment');
    expect(k).toContain('ssa-data-quality');
    expect(k).toContain('school-upload-quality');
    expect(k).toContain('activity-code-verification');
  });

  it('CD → Accountant includes fund/payment/disbursement', () => {
    const k = keys('CountryDirector', 'ProgramAccountant');
    expect(k).toContain('fund-request-status');
    expect(k).toContain('disbursement');
    expect(k).toContain('partner-payment');
  });

  it('CD → RVP includes country budget approval + strategic risk', () => {
    const k = keys('CountryDirector', 'RegionalVicePresident');
    expect(k).toContain('country-budget-approval');
    expect(k).toContain('strategic-risk');
  });
});

describe('PL / CCEO role-specific contexts', () => {
  it('PL → CCEO contexts are role-specific (target progress, evidence returned)', () => {
    const k = keys('CountryProgramLead', 'CCEO');
    expect(k).toContain('target-progress');
    expect(k).toContain('evidence-returned');
    expect(k).toContain('rescheduling-pattern');
  });

  it('CCEO → CD includes field issues, school risks, fund concerns', () => {
    const k = keys('CCEO', 'CountryDirector');
    expect(k).toContain('field-escalation');
    expect(k).toContain('major-school-issue');
    expect(k).toContain('school-improvement-concern');
    expect(k).toContain('fund-request-clarification');
  });

  it('CCEO cannot select an irrelevant CD-only context', () => {
    // "country-budget-approval" is a CD→RVP context, never a CCEO→CD one.
    expect(resolveContext('CCEO', 'CountryDirector', 'country-budget-approval')).toBeNull();
  });
});

describe('recipient scope (spec §7)', () => {
  it('Partner can message CCEO/PL/Accountant but NOT RVP or another partner', () => {
    expect(canMessageRole('PartnerFieldOfficer', 'CCEO')).toBe(true);
    expect(canMessageRole('PartnerFieldOfficer', 'ProgramAccountant')).toBe(true);
    expect(canMessageRole('PartnerFieldOfficer', 'RegionalVicePresident')).toBe(false);
    expect(canMessageRole('PartnerFieldOfficer', 'PartnerAdmin')).toBe(false);
  });

  it('Partner cannot message unrelated staff (HR, IA, CD)', () => {
    expect(canMessageRole('PartnerFieldOfficer', 'HumanResources')).toBe(false);
    expect(canMessageRole('PartnerFieldOfficer', 'ImpactAssessment')).toBe(false);
    expect(canMessageRole('PartnerFieldOfficer', 'CountryDirector')).toBe(false);
  });

  it('RVP cannot message partners by default', () => {
    expect(canMessageRole('RegionalVicePresident', 'PartnerFieldOfficer')).toBe(false);
    expect(canMessageRole('RegionalVicePresident', 'CountryDirector')).toBe(true);
  });

  it('HR can message staff but not partners by default', () => {
    expect(canMessageRole('HumanResources', 'CCEO')).toBe(true);
    expect(canMessageRole('HumanResources', 'PartnerFieldOfficer')).toBe(false);
  });

  it('allowedRecipientRoles is derived from the matrix', () => {
    const cd = allowedRecipientRoles('CountryDirector');
    expect(cd).toContain('CCEO');
    expect(cd).toContain('ImpactAssessment');
    expect(cd).toContain('RegionalVicePresident');
  });

  it('Admin may message everyone', () => {
    expect(canMessageRole('Admin', 'PartnerFieldOfficer')).toBe(true);
    expect(canMessageRole('Admin', 'RegionalVicePresident')).toBe(true);
  });
});

describe('checkMessagePolicy (send-path enforcement, spec §5)', () => {
  it('rejects when no context is selected', () => {
    const res = checkMessagePolicy({ senderRole: 'CountryDirector', recipientRole: 'CCEO', contextKey: '' });
    expect(res.ok).toBe(false);
  });

  it('rejects an off-policy recipient', () => {
    const res = checkMessagePolicy({ senderRole: 'PartnerFieldOfficer', recipientRole: 'RegionalVicePresident', contextKey: 'payment-status' });
    expect(res.ok).toBe(false);
  });

  it('rejects an off-policy context for an allowed pairing', () => {
    const res = checkMessagePolicy({ senderRole: 'CCEO', recipientRole: 'CountryDirector', contextKey: 'country-budget-approval' });
    expect(res.ok).toBe(false);
  });

  it('requires a linked record when the context demands one', () => {
    // "school-improvement-concern" requiresLinkedRecord = true.
    const noRecord = checkMessagePolicy({ senderRole: 'CCEO', recipientRole: 'CountryDirector', contextKey: 'school-improvement-concern' });
    expect(noRecord.ok).toBe(false);
    const withRecord = checkMessagePolicy({ senderRole: 'CCEO', recipientRole: 'CountryDirector', contextKey: 'school-improvement-concern', contextId: 'school:hope' });
    expect(withRecord.ok).toBe(true);
  });

  it('accepts a valid, record-less context', () => {
    const res = checkMessagePolicy({ senderRole: 'CountryDirector', recipientRole: 'CCEO', contextKey: 'performance-progress' });
    expect(res.ok).toBe(true);
    if (res.ok) expect(res.context.label).toBe('Performance and target progress');
  });
});
