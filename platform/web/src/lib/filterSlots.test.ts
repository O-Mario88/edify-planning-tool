import { describe, expect, it } from 'vitest';

import { arrangesRow, filterFields, filterSlots, foldFilters, UNMEASURED_SLOTS } from './filterSlots';

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

describe('foldFilters (a page that authors its own More filters)', () => {
  const named = (names: string, more = '') => names.split(' ').map((name) => ({ name, more: more.split(' ').includes(name) }));
  const clusters = named('fy quarter district sub_county staff ssa_status cluster_risk activity_status', 'ssa_status cluster_risk activity_status');
  const names = (list: readonly { name: string }[]) => list.map((f) => f.name).join(' ');

  it('keeps the authored three under More and the other five in the row at 1440 (six slots)', () => {
    const { inRow, folded } = foldFilters(clusters, 6, false, true);
    expect(names(inRow)).toBe('fy quarter district sub_county staff');
    expect(names(folded)).toBe('ssa_status cluster_risk activity_status');
  });

  it('moves the row’s last fields in front of the authored ones when the row is narrower', () => {
    const { inRow, folded } = foldFilters(clusters, filterSlots(360, true), true, true);
    expect(names(inRow)).toBe('fy quarter district');
    expect(names(folded)).toBe('sub_county staff ssa_status cluster_risk activity_status');
  });

  it('folds only the authored ones on a page that keeps its own grid', () => {
    const { inRow, folded } = foldFilters(clusters, 3, false, false);
    expect(names(inRow)).toBe('fy quarter district sub_county staff');
    expect(names(folded)).toBe('ssa_status cluster_risk activity_status');
  });

  it('folds by width alone when nothing is authored, as before', () => {
    const plain = named('a b c d e f g h');
    expect(names(foldFilters(plain, 7, false, true).inRow)).toBe('a b c d e f');
    expect(names(foldFilters(plain, 7, false, false).folded)).toBe('');
  });
});
