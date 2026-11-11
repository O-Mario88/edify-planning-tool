/**
 * What the Admin's Users screen shows and offers, as plain functions (owner,
 * 2026-10-09: "the Action button should include configure option so that the
 * admin can set up the account, reset passwords for all users" … "Add
 * deactivate option too for active users and activate for inactive users").
 */
import type { ManagedAccount } from '../../gen/edify/identity/v1/accounts_pb';

/** The existing role values (apps/core/rbac.py EdifyRole) and how they read. */
export const ROLES: readonly { readonly value: string; readonly label: string }[] = [
  { value: 'CCEO', label: 'CCEO' },
  { value: 'Program Lead', label: 'Program Lead' },
  { value: 'CountryDirector', label: 'Country Director' },
  { value: 'RegionalVicePresident', label: 'Regional Vice President' },
  { value: 'RegionalProgramLead', label: 'Regional Program Lead' },
  { value: 'ImpactAssessment', label: 'Impact Assessment' },
  { value: 'Accountant', label: 'Accountant' },
  { value: 'HumanResources', label: 'Human Resources' },
  { value: 'ProjectCoordinator', label: 'Project Coordinator' },
  { value: 'PartnerAdmin', label: 'Partner Admin' },
  { value: 'PartnerFieldOfficer', label: 'Partner Field Officer' },
  { value: 'BusinessTransformationOfficer', label: 'Business Transformation Officer' },
  { value: 'MfiPartnerAdmin', label: 'MFI Partner Admin' },
  { value: 'MfiLoanOfficer', label: 'MFI Loan Officer' },
  { value: 'Admin', label: 'Admin' },
  { value: 'ClusterLeader', label: 'Cluster Leader' },
];

export function roleLabel(role: string): string {
  return ROLES.find((choice) => choice.value === role)?.label ?? role;
}

/** The status filter, as the web's Users page offers it. */
export const STATUS_FILTERS: readonly { readonly value: string; readonly label: string }[] = [
  { value: '', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'pending_invited', label: 'Invited' },
  { value: 'suspended', label: 'Deactivated' },
  { value: 'disabled', label: 'Disabled' },
];

/** An account's status in words and colour (green active, blue invited, red closed). */
export function statusOf(account: Pick<ManagedAccount, 'status'>): { readonly label: string; readonly tone: string } {
  switch (account.status) {
    case 'active':
      return { label: 'Active', tone: 'good' };
    case 'pending_invited':
      return { label: 'Invited', tone: 'info' };
    case 'suspended':
      return { label: 'Deactivated', tone: 'caution' };
    case 'disabled':
      return { label: 'Disabled', tone: 'alert' };
  }
  return { label: account.status, tone: 'plain' };
}

export type AccountAction =
  | 'configure'
  | 'reset'
  | 'resend'
  | 'revoke'
  | 'unlock'
  | 'deactivate'
  | 'activate'
  | 'remove';

/**
 * The row's Actions menu: Configure and Reset password always; the
 * invitation's own actions while one is waiting; Unlock while locked;
 * Deactivate for an active account, Activate for an inactive one; Remove
 * last, never for the Admin themselves.
 */
export function actionsFor(
  account: Pick<ManagedAccount, 'status' | 'invitationStatus' | 'locked' | 'userId'>,
  selfId: string,
): AccountAction[] {
  const actions: AccountAction[] = ['configure', 'reset'];
  if (account.status === 'pending_invited') {
    actions.push('resend');
    if (account.invitationStatus === 'pending') {
      actions.push('revoke');
    }
  }
  if (account.locked) {
    actions.push('unlock');
  }
  if (account.userId !== selfId) {
    if (account.status === 'active') {
      actions.push('deactivate');
    } else if (account.status !== 'pending_invited') {
      actions.push('activate');
    }
    actions.push('remove');
  }
  return actions;
}

export const ACTION_LABELS: Readonly<Record<AccountAction, string>> = {
  configure: 'Configure',
  reset: 'Reset password',
  resend: 'Resend invitation',
  revoke: 'Revoke invitation',
  unlock: 'Unlock',
  deactivate: 'Deactivate',
  activate: 'Activate',
  remove: 'Remove account',
};

/** "Signed in 3 Nov 2026", or that they never have. */
export function lastSignIn(iso: string): string {
  const at = iso ? new Date(iso) : null;
  if (!at || Number.isNaN(at.getTime())) {
    return 'Never signed in';
  }
  return `Signed in ${at.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`;
}
