/**
 * What the partner leader's Team screen shows and offers (owner, 2026-10-09:
 * "partner admin onboard their team members and configure their logins";
 * "Partner can assign schools assigned to them to the rest of their team
 * members").
 */
import type { PartnerMemberInfo } from '../../gen/edify/identity/v1/teams_pb';

export type MemberAction = 'login' | 'reset' | 'deactivate' | 'activate' | 'schools' | 'remove';

export const MEMBER_ACTION_LABELS: Readonly<Record<MemberAction, string>> = {
  login: 'Give a login',
  reset: 'Reset password',
  deactivate: 'Deactivate login',
  activate: 'Activate login',
  schools: 'Schools',
  remove: 'Remove from team',
};

/**
 * A member's Actions menu: the team's leader gives logins, resets and
 * switches them, and splits the schools; whoever manages the roster removes
 * people. The leader's own login is never switched off from here.
 */
export function memberActions(
  member: Pick<PartnerMemberInfo, 'login'>,
  can: { readonly leadsTeam: boolean; readonly managesRoster: boolean },
  selfUserId: string,
): MemberAction[] {
  const actions: MemberAction[] = [];
  if (can.leadsTeam) {
    if (!member.login) {
      actions.push('login');
    } else {
      actions.push('reset');
      if (member.login.userId !== selfUserId) {
        actions.push(member.login.isActive ? 'deactivate' : 'activate');
      }
    }
    actions.push('schools');
  }
  if (can.managesRoster) {
    actions.push('remove');
  }
  return actions;
}

/** A member's sign-in in words and colour. */
export function loginOf(member: Pick<PartnerMemberInfo, 'login'>): { readonly label: string; readonly tone: string } {
  if (!member.login) {
    return { label: 'No login', tone: 'plain' };
  }
  if (member.login.status === 'pending_invited') {
    return { label: 'Invited', tone: 'info' };
  }
  return member.login.isActive ? { label: 'Login active', tone: 'good' } : { label: 'Login off', tone: 'caution' };
}

/** "3 schools", "1 school", "No schools". */
export function schoolsLabel(count: number): string {
  if (count === 0) {
    return 'No schools';
  }
  return `${count} ${count === 1 ? 'school' : 'schools'}`;
}
