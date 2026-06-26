import { describe, it, expect } from 'vitest';
import {
  dbPriority,
  NOTIFICATION_RULES,
  renderRule,
  resolveRecipients,
  ruleFor,
} from './notification-rules';

// Spec §20 — notification rule engine tests. These lock the event→notification
// mapping: every workflow event has a rule with a route-able context, the right
// priority (§14), and the right audience (§15).

describe('rule integrity', () => {
  it('every rule carries a context type, title and audience', () => {
    for (const r of NOTIFICATION_RULES) {
      expect(r.contextType, `${r.event} contextType`).toBeTruthy();
      expect(r.title, `${r.event} title`).toBeTruthy();
      expect(r.audience.length, `${r.event} audience`).toBeGreaterThan(0);
    }
  });

  it('maps spec priorities to DB enum values', () => {
    expect(dbPriority('critical')).toBe('urgent');
    expect(dbPriority('medium')).toBe('normal');
    expect(dbPriority('high')).toBe('high');
    expect(dbPriority('low')).toBe('low');
  });

  it('returns null for an unknown event (health-check gap)', () => {
    expect(ruleFor('NoSuchEvent')).toBeNull();
  });
});

describe('activity timing notifications (spec §10.A / §14)', () => {
  it('assigned activity notifies the assignee with action required', () => {
    const rule = ruleFor('ActivityAssignedToPartner')!;
    expect(rule.actionRequired).toBe(true);
    const ids = resolveRecipients(rule, { assignee: 'u-partner' });
    expect(ids).toEqual(['u-partner']);
  });

  it('past due is urgent and reaches assignee + supervisor', () => {
    const rule = ruleFor('ActivityPastDue')!;
    expect(dbPriority(rule.priority)).toBe('urgent');
    const ids = resolveRecipients(rule, { assignee: 'a', supervisorIds: ['s1', 's2'] });
    expect(ids.sort()).toEqual(['a', 's1', 's2']);
  });

  it('due soon is a medium reminder to the assignee', () => {
    const rule = ruleFor('ActivityDueSoon')!;
    expect(dbPriority(rule.priority)).toBe('normal');
    expect(rule.actionRequired).toBe(true);
  });
});

describe('evidence notifications (spec §10.B)', () => {
  it('evidence returned routes to the corrector', () => {
    const rule = ruleFor('EvidenceReturned')!;
    const ids = resolveRecipients(rule, { correctorId: 'owner', assignee: 'someone-else' });
    expect(ids).toEqual(['owner']);
  });
});

describe('planning gap notifications (spec §10.C)', () => {
  it('SSA missing is critical and fans to owner + PL + IA + CD summary', () => {
    const rule = ruleFor('SSAMissing')!;
    expect(dbPriority(rule.priority)).toBe('urgent');
    const ids = resolveRecipients(rule, {
      accountOwnerId: 'owner',
      usersByRole: { CountryProgramLead: ['pl'], ImpactAssessment: ['ia'], CountryDirector: ['cd'] },
    });
    expect(ids).toContain('owner');
    expect(ids).toContain('pl');
    expect(ids).toContain('ia');
    expect(ids).toContain('cd');
  });

  it('school not visited reaches owner + PL + CD summary', () => {
    const rule = ruleFor('SchoolNotVisited')!;
    const ids = resolveRecipients(rule, { accountOwnerId: 'o', usersByRole: { CountryProgramLead: ['pl'], CountryDirector: ['cd'] } });
    expect(ids.sort()).toEqual(['cd', 'o', 'pl']);
  });
});

describe('school improvement notifications (spec §10.D)', () => {
  it('potential core notifies CCEO, PL, CD, IA', () => {
    const rule = ruleFor('PotentialCoreFlagged')!;
    const ids = resolveRecipients(rule, {
      usersByRole: { CCEO: ['cceo'], CountryProgramLead: ['pl'], CountryDirector: ['cd'], ImpactAssessment: ['ia'] },
    });
    expect(ids.sort()).toEqual(['cceo', 'cd', 'ia', 'pl']);
  });

  it('champion school notification is low priority', () => {
    const rule = ruleFor('ChampionSchoolFlagged')!;
    expect(dbPriority(rule.priority)).toBe('low');
  });
});

describe('fund request routing notifications (spec §11)', () => {
  it('covers the PL → CD → RVP → Accountant chain', () => {
    expect(ruleFor('FundRequestApprovedByPL')).toBeTruthy();
    expect(ruleFor('FundRequestApprovedByCD')).toBeTruthy();
    expect(ruleFor('FundRequestSubmittedToRVP')).toBeTruthy();
    expect(ruleFor('FundRequestApprovedByRVP')).toBeTruthy();
  });

  it('ApprovedByCD notifies submitter + RVP summary', () => {
    const rule = ruleFor('FundRequestApprovedByCD')!;
    const ids = resolveRecipients(rule, { submitter: 'sub', usersByRole: { RegionalVicePresident: ['rvp'] } });
    expect(ids.sort()).toEqual(['rvp', 'sub']);
  });

  it('ApprovedByRVP notifies CD and Accountant', () => {
    const rule = ruleFor('FundRequestApprovedByRVP')!;
    const ids = resolveRecipients(rule, { usersByRole: { CountryDirector: ['cd'], ProgramAccountant: ['acc'] } });
    expect(ids.sort()).toEqual(['acc', 'cd']);
  });
});

describe('FY-end notifications (spec §10.E)', () => {
  it('FY-end risk is critical and reaches PL + CD + RVP summary', () => {
    const rule = ruleFor('FYEndRiskDetected')!;
    expect(dbPriority(rule.priority)).toBe('urgent');
    const ids = resolveRecipients(rule, { usersByRole: { CountryProgramLead: ['pl'], CountryDirector: ['cd'], RegionalVicePresident: ['rvp'] } });
    expect(ids.sort()).toEqual(['cd', 'pl', 'rvp']);
  });
});

describe('renderRule', () => {
  it('interpolates name + detail and trims the empty "{name}: " prefix', () => {
    const rule = ruleFor('PartnerScheduledActivity')!;
    const { title, body } = renderRule(rule, { name: 'Jane', detail: 'Kireka visit' });
    expect(title).toBe('Partner scheduled an activity');
    expect(body).toBe('Jane: Kireka visit');
    const empty = renderRule(rule, { detail: 'Kireka visit' });
    expect(empty.body).toBe('Kireka visit');
  });
});
