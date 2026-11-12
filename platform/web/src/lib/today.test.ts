import { describe, expect, it } from 'vitest';

import { dateChip, initialsOf } from './today';

describe('dateChip', () => {
  it('reads Kampala’s day and its ISO week', () => {
    expect(dateChip(new Date('2026-11-12T08:00:00Z'))).toEqual({ weekday: 'THU', date: 'Nov 12, 2026', week: 46 });
    // 22:30 UTC on the 12th is already the 13th in Kampala (UTC+3).
    expect(dateChip(new Date('2026-11-12T22:30:00Z')).date).toBe('Nov 13, 2026');
    expect(dateChip(new Date('2027-01-01T09:00:00Z')).week).toBe(53);
  });
});

describe('initialsOf', () => {
  it('takes the first and last name, else the email', () => {
    expect(initialsOf('Paul N. Okello', 'p@x')).toBe('PO');
    expect(initialsOf('', 'cceo@edify.org')).toBe('CC');
  });
});
