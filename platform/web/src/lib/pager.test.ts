import { describe, expect, it } from 'vitest';

import { elidedPageNumbers, hrefWith, showingSummary } from './pager';

describe('elidedPageNumbers (Django get_elided_page_range, 1 each side, 1 at the ends)', () => {
  it.each([
    [1, 1, [1]],
    [1, 4, [1, 2, 3, 4]],
    [1, 14, [1, 2, null, 14]],
    [2, 14, [1, 2, 3, null, 14]],
    [4, 14, [1, 2, 3, 4, 5, null, 14]],
    [5, 14, [1, null, 4, 5, 6, null, 14]],
    [11, 14, [1, null, 10, 11, 12, 13, 14]],
    [14, 14, [1, null, 13, 14]],
    [99, 14, [1, null, 13, 14]],
  ])('page %i of %i', (current, total, expected) => {
    expect(elidedPageNumbers(current, total)).toEqual(expected);
  });
});

describe('showingSummary', () => {
  it('words the range as the existing pager does', () => {
    expect(showingSummary(1, 50, 699, 'schools')).toBe('Showing 1 to 50 of 699 schools');
    expect(showingSummary(14, 50, 699, 'schools')).toBe('Showing 651 to 699 of 699 schools');
  });
});

describe('hrefWith', () => {
  it('sets and drops keys', () => {
    expect(hrefWith('/schools', { tab: 'clustered', page: '2' }, { page: '' })).toBe('/schools?tab=clustered');
    expect(hrefWith('/schools', {}, {})).toBe('/schools');
  });
});
