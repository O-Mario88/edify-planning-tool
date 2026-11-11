import {
  CLUSTER_TABS,
  LEADERS_URL,
  canManageLeaders,
  clusterBottomBar,
  clusterWorkSection,
  dateBox,
  leadersSection,
  longDate,
  tabOf,
  tabOfUrl,
} from '../screens/cluster/clusterRoutes';

describe('the Cluster Leader portal routes', () => {
  test("the bottom bar is the mockup's Home, Meetings and Schools, all drawn natively", () => {
    const bar = clusterBottomBar();
    expect(bar.map((item) => item.label)).toEqual(['Home', 'Meetings', 'Schools']);
    expect(bar.every((item) => item.native && item.iconSvg.startsWith('<svg'))).toBe(true);
  });

  test('More keeps the follow-up, reports, cluster and the loan link one tap away', () => {
    const labels = clusterWorkSection().items.map((item) => item.label);
    expect(labels).toEqual(['Action & follow-up', 'Requests to staff', 'Progress & Reports', 'Manage cluster', 'Share loan application']);
    expect(clusterWorkSection().items.map((item) => tabOfUrl(item.url))).toEqual(['actions', 'requests', 'progress', 'manage', 'share']);
  });

  test("a Home count's link opens the tab it counts", () => {
    expect(tabOf('schools')).toBe('schools');
    // Home's older links to Activities and plans open Meetings.
    expect(tabOf('activities?when=upcoming')).toBe('meetings');
    expect(tabOf('plans')).toBe('meetings');
    expect(tabOf('')).toBe('home');
    expect(tabOf('/settings')).toBeNull();
  });

  test('a shell URL is its tab, the menu is none', () => {
    expect(tabOfUrl(CLUSTER_TABS.schools)).toBe('schools');
    expect(tabOfUrl('app:menu')).toBeNull();
  });
});

describe('who sees Cluster Leaders', () => {
  test('the managing roles do; others and Cluster Leaders do not', () => {
    expect(canManageLeaders('Admin')).toBe(true);
    expect(canManageLeaders('Program Lead')).toBe(true);
    expect(canManageLeaders('CCEO')).toBe(true);
    expect(canManageLeaders('ClusterLeader')).toBe(false);
    expect(canManageLeaders('Accountant')).toBe(false);
  });

  test('the menu section opens the native screen', () => {
    const section = leadersSection();
    expect(section.items.map((item) => [item.url, item.native])).toEqual([[LEADERS_URL, true]]);
  });
});

describe('dates', () => {
  test('a date box shows the month and day', () => {
    expect(dateBox('2026-11-15')).toEqual({ month: 'NOV', day: '15' });
    expect(dateBox('')).toEqual({ month: '', day: '' });
  });

  test('a long date reads as the web writes it, or says it is not set', () => {
    expect(longDate('2026-01-05')).toBe('5 Jan 2026');
    expect(longDate('')).toBe('Date to be set');
  });
});
