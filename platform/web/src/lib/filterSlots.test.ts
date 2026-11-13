import { describe, expect, it } from 'vitest';

import { arrangesRow, filterFields, filterSlots, UNMEASURED_SLOTS } from './filterSlots';

describe('filterSlots and filterFields (micro-ux.js)', () => {
  it('fits one 144px slot and a 12px gap a filter, at least three', () => {
    expect(filterSlots(1120, false)).toBe(7);
    expect(filterSlots(300, false)).toBe(3);
    expect(filterSlots(0, false)).toBe(UNMEASURED_SLOTS);
  });

  it('folds the filters past the last slot under More, which takes that slot', () => {
    expect(filterFields(8, 7, false)).toBe(6);
    expect(filterFields(6, 7, false)).toBe(6);
    expect(filterFields(7, 7, false)).toBe(7);
  });

  it('keeps three on a phone and folds the rest', () => {
    expect(filterFields(8, filterSlots(360, true), true)).toBe(3);
    expect(filterFields(3, filterSlots(360, true), true)).toBe(3);
  });
});

describe('arrangesRow', () => {
  it('lays out a row of three or more on a wide screen, two or more on a phone; fewer keep their own width (micro-ux.js)', () => {
    expect(arrangesRow(2, false)).toBe(false);
    expect(arrangesRow(3, false)).toBe(true);
    expect(arrangesRow(1, true)).toBe(false);
    expect(arrangesRow(2, true)).toBe(true);
  });
});
