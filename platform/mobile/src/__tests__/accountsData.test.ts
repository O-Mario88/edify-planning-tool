import { actionsFor, lastSignIn, roleLabel, statusOf } from '../screens/admin/accountsData';

const base = { status: 'active', invitationStatus: 'accepted', locked: false, userId: 'u1' };

describe("the Users screen's row Actions (owner, 2026-10-09)", () => {
  test('an active account can be configured, reset, deactivated and removed', () => {
    expect(actionsFor(base, 'admin')).toEqual(['configure', 'reset', 'deactivate', 'remove']);
  });

  test('an inactive account is activated rather than deactivated', () => {
    expect(actionsFor({ ...base, status: 'suspended' }, 'admin')).toEqual(['configure', 'reset', 'activate', 'remove']);
  });

  test("an invited account offers its invitation's own actions", () => {
    expect(actionsFor({ ...base, status: 'pending_invited', invitationStatus: 'pending' }, 'admin')).toEqual([
      'configure',
      'reset',
      'resend',
      'revoke',
      'remove',
    ]);
    expect(actionsFor({ ...base, status: 'pending_invited', invitationStatus: 'expired' }, 'admin')).not.toContain('revoke');
  });

  test('a locked account can be unlocked', () => {
    expect(actionsFor({ ...base, locked: true }, 'admin')).toContain('unlock');
  });

  test('the Admin never deactivates or removes their own account', () => {
    expect(actionsFor({ ...base, userId: 'admin' }, 'admin')).toEqual(['configure', 'reset']);
  });
});

describe('how an account reads', () => {
  test('status in words and colour', () => {
    expect(statusOf({ status: 'active' })).toEqual({ label: 'Active', tone: 'good' });
    expect(statusOf({ status: 'pending_invited' })).toEqual({ label: 'Invited', tone: 'info' });
    expect(statusOf({ status: 'suspended' })).toEqual({ label: 'Deactivated', tone: 'caution' });
  });

  test('roles by their names, and the last sign-in', () => {
    expect(roleLabel('CountryDirector')).toBe('Country Director');
    expect(roleLabel('Program Lead')).toBe('Program Lead');
    expect(lastSignIn('')).toBe('Never signed in');
    expect(lastSignIn('2026-11-03T09:00:00Z')).toBe('Signed in 3 Nov 2026');
  });
});
