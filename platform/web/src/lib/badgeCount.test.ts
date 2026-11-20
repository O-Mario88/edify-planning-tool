import { describe, expect, it } from 'vitest';

import { badgeCount, unreadName } from './badgeCount';

describe('badgeCount', () => {
  it('draws nothing for none, the figure up to 99, and 99+ past two digits (frontend_filters.badge_count)', () => {
    expect(badgeCount(0)).toBe('');
    expect(badgeCount(-1)).toBe('');
    expect(badgeCount(4)).toBe('4');
    expect(badgeCount(99)).toBe('99');
    expect(badgeCount(100)).toBe('99+');
    expect(badgeCount(138)).toBe('99+');
  });
});

describe('unreadName', () => {
  it('names the control with the figure its badge shows, and alone when it shows none', () => {
    expect(unreadName('Notifications', 0)).toBe('Notifications');
    expect(unreadName('Notifications', 4)).toBe('Notifications, 4 unread');
    expect(unreadName('Messages', 138)).toBe('Messages, 99+ unread');
  });
});
