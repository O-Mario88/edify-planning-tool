import { create, fromJson } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { PageBlockSchema, PageChartSchema, PageTabSchema } from '@/gen/edify/screens/v1/page_pb';

import { barParts, chartAxis, chartValue, profileAsk, profileTabs, profileYear, splitRail, trailingPanels } from './schoolProfile';

const block = (json: object) => fromJson(PageBlockSchema, json as never);

describe('profileAsk', () => {
  it('carries the tab, year and period the profile request takes', () => {
    expect(profileAsk({ tab: 'ssa', fy: '2026', period: 'Q1' })).toEqual({ tab: 'ssa', fy: '2026', period: 'Q1', elsewhere: false });
    expect(profileAsk({})).toEqual({ tab: '', fy: '', period: '', elsewhere: false });
  });

  it('leaves a list a figure opens (what=…) to the existing web', () => {
    expect(profileAsk({ fy: '2027', what: 'intervention', key: 'leadership' }).elsewhere).toBe(true);
  });
});

describe('profileTabs', () => {
  const tabs = [create(PageTabSchema, { key: 'overview', label: 'Overview', active: true }), create(PageTabSchema, { key: 'activities', label: 'Participation' })];

  it('links each tab on the profile’s path with the year, never the period (partials/profiles/_tabs.html)', () => {
    const rail = profileTabs(tabs, '/schools/1000', '2026');
    expect(rail.tabs.map((tab) => tab.href)).toEqual(['/schools/1000?tab=overview&fy=2026', '/schools/1000?tab=activities&fy=2026']);
    expect(rail.tabs.map((tab) => tab.active)).toEqual([true, false]);
  });

  it('leaves the year out where none is known', () => {
    expect(profileTabs(tabs, '/schools/1000', '').tabs[1]?.href).toBe('/schools/1000?tab=activities');
  });
});

describe('profileYear', () => {
  it('reads the year filter’s value, else the year asked', () => {
    const blocks = [block({ filters: { filters: [{ name: 'fy', label: 'Fiscal year', value: '2027' }] } })];
    expect(profileYear(blocks, '2025')).toBe('2027');
    expect(profileYear([block({ panel: { title: 'Details' } })], '2025')).toBe('2025');
  });
});

describe('splitRail', () => {
  it('keeps the frame above, the rail apart and the rest in order', () => {
    const blocks = [block({ scopeLine: 'Single school' }), block({ facts: {} }), block({ filters: {} }), block({ strip: {} }), block({ table: {} }), block({ rail: { title: 'Profile Insights' } })];
    const { frame, main, rail } = splitRail(blocks);
    expect(frame.map((b) => b.kind.case)).toEqual(['scopeLine', 'facts', 'filters']);
    expect(main.map((b) => b.kind.case)).toEqual(['strip', 'table']);
    expect(rail.map((b) => b.kind.case)).toEqual(['rail']);
  });

  it('draws a tab without a rail as one column', () => {
    const { frame, main, rail } = splitRail([block({ panel: {} })]);
    expect([frame.length, main.length, rail.length]).toEqual([0, 1, 0]);
  });
});

describe('trailingPanels', () => {
  it('finds the run of two or more cards that ends the tab', () => {
    expect(trailingPanels([block({ table: {} }), block({ chart: {} }), block({ panel: {} }), block({ panel: {} })])).toBe(2);
    expect(trailingPanels([block({ table: {} }), block({ panel: {} })])).toBe(2);
    expect(trailingPanels([block({ panel: {} }), block({ table: {} })])).toBe(2);
  });
});

describe('chartAxis', () => {
  it('runs an SSA chart from 0 to its ceiling of 10 in steps of 2', () => {
    const chart = create(PageChartSchema, { max: 10, series: [{ name: 'a', values: [6.25] }] });
    expect(chartAxis(chart)).toEqual({ min: 0, max: 10, ticks: [0, 2, 4, 6, 8, 10] });
  });

  it('runs to the largest value where the chart names no ceiling', () => {
    const chart = create(PageChartSchema, { series: [{ name: 'a', values: [3, 47] }] });
    const axis = chartAxis(chart);
    expect(axis.max).toBe(47);
    expect(axis.ticks[0]).toBe(0);
    expect(axis.ticks.at(-1)).toBeLessThanOrEqual(47);
  });
});

describe('barParts', () => {
  it('draws two series as a cut-out: the shorter inside, the longer’s remainder beyond', () => {
    // Christlike Behaviour: FY 2025/26 6.6, FY 2026/27 6.4.
    const parts = barParts([6.6, 6.4], 0, 10);
    expect(parts.map((part) => [part.series, part.value, part.inside])).toEqual([
      [1, 6.4, true],
      [0, 6.6, false],
    ]);
    expect(parts[0]?.from).toBe(0);
    expect(parts[0]?.to).toBeCloseTo(0.64, 9);
    expect(parts[1]?.from).toBeCloseTo(0.64, 9);
    expect(parts[1]?.to).toBeCloseTo(0.66, 9);
    // Government Requirements: 5.8 then 6.1.
    expect(barParts([5.8, 6.1], 0, 10).map((part) => [part.series, part.value, part.inside])).toEqual([
      [0, 5.8, true],
      [1, 6.1, false],
    ]);
  });

  it('draws one series as a plain bar with its figure beyond', () => {
    expect(barParts([6.25], 0, 10)).toEqual([{ series: 0, from: 0, to: 0.625, value: 6.25, inside: false }]);
  });

  it('draws one bar where a year has no value, and holds a value inside the axis', () => {
    expect(barParts([Number.NaN, 7], 0, 10)).toEqual([{ series: 1, from: 0, to: 0.7, value: 7, inside: false }]);
    expect(barParts([12], 0, 10)[0]?.to).toBe(1);
  });
});

describe('chartValue', () => {
  it('writes a value as the existing chart does', () => {
    expect([chartValue(6), chartValue(6.25), chartValue(5.9), chartValue(0.1 + 0.2)]).toEqual(['6', '6.25', '5.9', '0.3']);
  });
});
