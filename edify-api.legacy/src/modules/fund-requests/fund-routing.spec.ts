import { describe, it, expect } from 'vitest';
import {
  approveTransition,
  isCurrentApprover,
  isReturned,
  isTerminal,
  returnTransition,
  submitTransition,
} from './fund-routing';

// Spec §11 + §20 — the fund request routing chain PL → CD → RVP → Accountant,
// including the country-scope RVP hop, the per-stage return path, and the event
// emitted at each transition (the events the rule engine routes).

describe('fund routing — forward chain (spec §11)', () => {
  it('submission enters the chain at PL', () => {
    expect(submitTransition()).toEqual({ status: 'submitted_to_pl', event: 'FundRequestSubmittedToPL' });
  });

  it('a COUNTRY request routes PL → CD → RVP → Accountant', () => {
    expect(approveTransition('submitted_to_pl', 'country')).toEqual({ status: 'submitted_to_cd', event: 'FundRequestApprovedByPL' });
    expect(approveTransition('submitted_to_cd', 'country')).toEqual({ status: 'submitted_to_rvp', event: 'FundRequestApprovedByCD' });
    expect(approveTransition('submitted_to_rvp', 'country')).toEqual({ status: 'sent_to_accountant', event: 'FundRequestApprovedByRVP' });
    expect(approveTransition('sent_to_accountant', 'country')).toEqual({ status: 'disbursed', event: 'FundsDisbursed' });
  });

  it('a TEAM request skips RVP — CD approval goes straight to the accountant', () => {
    expect(approveTransition('submitted_to_cd', 'team')).toEqual({ status: 'sent_to_accountant', event: 'FundRequestApprovedByCD' });
  });

  it('does not advance from a terminal/return status', () => {
    expect(approveTransition('disbursed', 'country')).toBeNull();
    expect(approveTransition('returned_by_cd', 'country')).toBeNull();
  });
});

describe('fund routing — returns route back to the submitter', () => {
  it('each stage returns with the right returned_by_* status', () => {
    expect(returnTransition('submitted_to_pl')).toEqual({ status: 'returned_by_pl', event: 'FundRequestReturned' });
    expect(returnTransition('submitted_to_cd')).toEqual({ status: 'returned_by_cd', event: 'FundRequestReturned' });
    expect(returnTransition('submitted_to_rvp')).toEqual({ status: 'returned_by_rvp', event: 'FundRequestReturned' });
    expect(returnTransition('sent_to_accountant')).toEqual({ status: 'returned_by_accountant', event: 'FundRequestReturned' });
  });

  it('cannot return a request that is not awaiting an approver', () => {
    expect(returnTransition('disbursed')).toBeNull();
    expect(returnTransition('draft')).toBeNull();
  });
});

describe('fund routing — guards', () => {
  it('identifies the role currently expected to approve', () => {
    expect(isCurrentApprover('submitted_to_pl', 'CountryProgramLead')).toBe(true);
    expect(isCurrentApprover('submitted_to_pl', 'CountryDirector')).toBe(false);
    expect(isCurrentApprover('submitted_to_rvp', 'RegionalVicePresident')).toBe(true);
  });

  it('classifies returned + terminal statuses', () => {
    expect(isReturned('returned_by_rvp')).toBe(true);
    expect(isReturned('submitted_to_cd')).toBe(false);
    expect(isTerminal('closed')).toBe(true);
    expect(isTerminal('disbursed')).toBe(true);
    expect(isTerminal('submitted_to_pl')).toBe(false);
  });
});
