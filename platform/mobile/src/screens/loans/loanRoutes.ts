/**
 * School loan referrals in the app: who finds them under their menu, and the
 * small rules the screens share. The gateway decides what each role may see
 * and do; these only decide where the pages are listed.
 */
import { create } from '@bufbuild/protobuf';

import type { NavSection } from '../../gen/edify/screens/v1/navigation_pb';
import { NavItemSchema, NavSectionSchema } from '../../gen/edify/screens/v1/navigation_pb';

export const LOANS_URL = 'loans:referrals';
export const LENDER_CHANNELS_URL = 'loans:lenders';
export const MY_REFERRALS_URL = 'loans:mine';

/** Edify staff who follow loan referrals (apps/core/rbac.py). Admin is not one. */
const STAFF_ROLES = new Set(['BusinessTransformationOfficer', 'CountryDirector', 'RegionalVicePresident']);
/** A lending partner's own staff. */
const LENDER_ROLES = new Set(['MfiPartnerAdmin', 'MfiLoanOfficer']);

export function isLenderRole(role: string): boolean {
  return LENDER_ROLES.has(role);
}

/** The loans section of the caller's menu, or null when they have none. */
export function loansSection(role: string): NavSection | null {
  const item = (label: string, url: string) => create(NavItemSchema, { label, url, native: true });
  if (STAFF_ROLES.has(role)) {
    return create(NavSectionSchema, {
      label: 'School loans',
      items: [item('Loan referrals', LOANS_URL), item('Lending partners', LENDER_CHANNELS_URL)],
    });
  }
  if (LENDER_ROLES.has(role)) {
    return create(NavSectionSchema, { label: 'School loans', items: [item('Referrals to us', MY_REFERRALS_URL)] });
  }
  return null;
}

export function isLoansUrl(url: string): boolean {
  return url === LOANS_URL || url === LENDER_CHANNELS_URL || url === MY_REFERRALS_URL;
}

/** An amount in whole Uganda shillings, grouped: "UGX 45,000,000". */
export function formatUGX(value: bigint | number): string {
  const digits = BigInt(value).toString();
  const negative = digits.startsWith('-');
  const plain = negative ? digits.slice(1) : digits;
  const grouped = plain.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `UGX ${negative ? '-' : ''}${grouped}`;
}

const GROUPED = /^\d{1,3}(,\d{3})+$/;

/** An amount typed as "38,500,000" or "UGX 1 500 000"; null when unclear. */
export function parseUGX(raw: string): bigint | null {
  let value = raw
    .trim()
    .replace(/^(ugx|ushs?\.?|shs?\.?)\s*/i, '')
    .replace(/\/=$/, '')
    .replace(/\s/g, '');
  if (value === '') {
    return null;
  }
  if (value.includes(',')) {
    if (!GROUPED.test(value)) {
      return null;
    }
    value = value.replace(/,/g, '');
  }
  return /^\d{1,12}$/.test(value) ? BigInt(value) : null;
}

/** The colour family of an application status. */
export function loanStatusTone(status: string): 'good' | 'alert' | 'caution' | 'info' | 'plain' {
  switch (status) {
    case 'approved':
    case 'disbursed':
    case 'closed':
      return 'good';
    case 'declined':
    case 'withdrawn':
      return 'alert';
    case 'information_requested':
    case 'submitted':
      return 'caution';
    default:
      return 'info';
  }
}

/** "2026-11-11T03:45:00Z" or "2026-11-11" as "11 Nov 2026" (empty for none). */
export function shortDate(stamp: string): string {
  if (!stamp) {
    return '';
  }
  const day = new Date(stamp.length === 10 ? `${stamp}T12:00:00Z` : stamp);
  if (Number.isNaN(day.getTime())) {
    return '';
  }
  return day.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Africa/Kampala' });
}

/** Today in Kampala as an ISO date. */
export function todayISO(now: Date = new Date()): string {
  return now.toLocaleDateString('en-CA', { timeZone: 'Africa/Kampala' });
}
