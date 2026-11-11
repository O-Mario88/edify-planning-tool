import {
  CLUSTER_TABS,
  LEADERS_URL,
  canManageLeaders,
  clusterBottomBar,
  dateBox,
  leadersSection,
  longDate,
  tabOf,
  tabOfUrl,
} from '../screens/cluster/clusterRoutes';

describe('the Cluster Leader portal routes', () => {
  test('the bottom bar is Home, Schools, Activities and the loan link, all drawn natively', () => {
    const bar = clusterBottomBar();
    expect(bar.map((item) => item.label)).toEqual(['Home', 'Schools', 'Activities', 'Loan link']);
    expect(bar.every((item) => item.native && item.iconSvg.startsWith('<svg'))).toBe(true);
  });

  test("a Home count's link opens the tab it counts", () => {
    expect(tabOf('schools')).toBe('schools');
    expect(tabOf('activities?when=upcoming')).toBe('activities');
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
