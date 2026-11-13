import { describe, expect, it } from 'vitest';

import { isEmptyFilter } from './emptyFilter';

describe('isEmptyFilter', () => {
  it('hides a filter with one option and nothing applied, as micro-ux.js does', () => {
    expect(isEmptyFilter({ value: 'All', options: [{}] })).toBe(true);
    expect(isEmptyFilter({ value: 'all', options: [] })).toBe(true);
    expect(isEmptyFilter({ value: '', options: [{}] })).toBe(true);
  });

  it('keeps a filter with a choice, or with a value applied', () => {
    expect(isEmptyFilter({ value: 'All', options: [{}, {}] })).toBe(false);
    expect(isEmptyFilter({ value: 'cmw9p546g', options: [{}] })).toBe(false);
  });
});
