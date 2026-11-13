import { describe, expect, it } from 'vitest';

import { stripRange } from './stripRange';

describe('stripRange (kpi-strips.js)', () => {
  it('counts the figures in view in first-cell widths', () => {
    expect(stripRange({ count: 10, cell: 140, width: 1120, scrollLeft: 0, scrollWidth: 1400 })).toEqual({
      overflow: true,
      start: 1,
      end: 8,
      thumbWidth: 0.8,
      thumbOffset: 0,
    });
    expect(stripRange({ count: 10, cell: 140, width: 1120, scrollLeft: 280, scrollWidth: 1400 })?.end).toBe(10);
  });

  it('draws no rail while every figure fits', () => {
    expect(stripRange({ count: 8, cell: 140, width: 1120, scrollLeft: 0, scrollWidth: 1121 })).toBeNull();
  });
});
