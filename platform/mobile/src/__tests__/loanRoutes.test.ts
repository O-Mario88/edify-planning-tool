import {
  LENDER_CHANNELS_URL,
  LOANS_URL,
  MY_REFERRALS_URL,
  formatUGX,
  isLoansUrl,
  loanStatusTone,
  loansSection,
  parseUGX,
  LENDER_CASES_URL,
  SHARE_URL,
  STAFF_LOANS_URL,
} from '../screens/loans/loanRoutes';

describe('loan referral routes', () => {
  it('gives BTO, Country Director and RVP the referral pages', () => {
    for (const role of ['BusinessTransformationOfficer', 'CountryDirector', 'RegionalVicePresident']) {
      const section = loansSection(role);
      expect(section?.items.map((item) => item.url)).toEqual([STAFF_LOANS_URL, LOANS_URL, LENDER_CHANNELS_URL, SHARE_URL]);
      expect(section?.items.every((item) => item.native)).toBe(true);
    }
  });

  it("gives a lender's own staff their cases, referrals and link", () => {
    for (const role of ['MfiPartnerAdmin', 'MfiLoanOfficer']) {
      expect(loansSection(role)?.items.map((item) => item.url)).toEqual([LENDER_CASES_URL, MY_REFERRALS_URL, SHARE_URL]);
    }
  });

  it("gives CCEOs and PLs their schools' loans and the share page", () => {
    for (const role of ['CCEO', 'Program Lead']) {
      expect(loansSection(role)?.items.map((item) => item.url)).toEqual([STAFF_LOANS_URL, SHARE_URL]);
    }
  });

  it('gives nobody else a loans section, Admin included', () => {
    for (const role of ['Admin', 'ClusterLeader', '']) {
      expect(loansSection(role)).toBeNull();
    }
  });

  it('knows its own routes', () => {
    expect(isLoansUrl(LOANS_URL)).toBe(true);
    expect(isLoansUrl(MY_REFERRALS_URL)).toBe(true);
    expect(isLoansUrl('/loans')).toBe(false);
  });

  it('writes UGX grouped, from the contract’s 64-bit integers', () => {
    expect(formatUGX(BigInt(45000000))).toBe('UGX 45,000,000');
    expect(formatUGX(0)).toBe('UGX 0');
    expect(formatUGX(BigInt(950))).toBe('UGX 950');
  });

  it('reads UGX as typed on a phone, and refuses anything unclear', () => {
    expect(parseUGX('38,500,000')).toBe(BigInt(38500000));
    expect(parseUGX('UGX 1 500 000')).toBe(BigInt(1500000));
    expect(parseUGX('')).toBeNull();
    expect(parseUGX('1.5m')).toBeNull();
    expect(parseUGX('12,34,5')).toBeNull();
    expect(parseUGX('-5')).toBeNull();
  });

  it('colours finished, refused and waiting statuses apart', () => {
    expect(loanStatusTone('disbursed')).toBe('good');
    expect(loanStatusTone('declined')).toBe('alert');
    expect(loanStatusTone('information_requested')).toBe('caution');
    expect(loanStatusTone('under_review')).toBe('info');
  });
});
