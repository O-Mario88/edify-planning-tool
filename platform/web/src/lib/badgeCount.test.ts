import { describe, expect, it } from 'vitest';

import { badgeCount } from './badgeCount';

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
