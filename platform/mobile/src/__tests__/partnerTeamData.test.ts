import { loginOf, memberActions, schoolsLabel } from '../screens/partner/partnerTeamData';

const leader = { leadsTeam: true, managesRoster: true };
const withLogin = (userId: string, isActive: boolean, status = 'active') => ({
  login: { userId, isActive, status } as never,
});

describe("the partner Team screen's member Actions (owner, 2026-10-09)", () => {
  test('a member without a login can be given one, given schools and removed', () => {
    expect(memberActions({ login: undefined }, leader, 'self')).toEqual(['login', 'schools', 'remove']);
  });

  test('an active login is reset or deactivated, an inactive one activated', () => {
    expect(memberActions(withLogin('u2', true), leader, 'self')).toEqual(['reset', 'deactivate', 'schools', 'remove']);
    expect(memberActions(withLogin('u2', false), leader, 'self')).toEqual(['reset', 'activate', 'schools', 'remove']);
  });

  test("the leader's own login is never switched off from here", () => {
    expect(memberActions(withLogin('self', true), leader, 'self')).toEqual(['reset', 'schools', 'remove']);
  });

  test('whoever only manages the roster can remove people and nothing else', () => {
    expect(memberActions({ login: undefined }, { leadsTeam: false, managesRoster: true }, 'self')).toEqual(['remove']);
  });

  test('a reader with neither power gets no menu', () => {
    expect(memberActions(withLogin('u2', true), { leadsTeam: false, managesRoster: false }, 'self')).toEqual([]);
  });
});

describe("a member's login badge and schools", () => {
  test('reads the login in words', () => {
    expect(loginOf({ login: undefined }).label).toBe('No login');
    expect(loginOf(withLogin('u2', false, 'pending_invited')).label).toBe('Invited');
    expect(loginOf(withLogin('u2', true)).label).toBe('Login active');
    expect(loginOf(withLogin('u2', false, 'suspended')).label).toBe('Login off');
  });

  test('counts schools', () => {
    expect(schoolsLabel(0)).toBe('No schools');
    expect(schoolsLabel(1)).toBe('1 school');
    expect(schoolsLabel(4)).toBe('4 schools');
  });
});
