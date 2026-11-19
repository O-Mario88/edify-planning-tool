import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { HomePriorityRowSchema, HomeUpcomingSchema } from '@/gen/edify/screens/v1/home_pb';

import { allClear, countedFigures, figureNumber, nextUp, toneOf, waitingRows } from './todayView';

const row = (key: string, over: Partial<{ count: number; statusTone: string }> = {}) =>
  create(HomePriorityRowSchema, { key, title: key, ...over });

describe('waitingRows', () => {
  it('leaves out a row that only reports nothing to do, and keeps Home’s order', () => {
    const rows = [
      row('overdue', { count: 8, statusTone: 'alert' }),
      row('unclustered', { count: 0, statusTone: 'good' }),
      row('task', { count: 0, statusTone: 'info' }),
      row('none-visited', { count: 3, statusTone: 'good' }),
    ];
    expect(waitingRows(rows).map((r) => r.key)).toEqual(['overdue', 'task', 'none-visited']);
    expect(allClear(rows[1]!)).toBe(true);
  });
});

describe('countedFigures', () => {
  it('keeps whole numbers above nought, in order', () => {
    const cards = ['4', '0', '1,204', 'No data', '', '0,000', '12%'].map((value, i) => ({ key: `k${i}`, value }));
    expect(countedFigures(cards).map((c) => c.value)).toEqual(['4', '1,204']);
    expect(figureNumber({ value: '1,204' })).toBe(1204);
  });
});

describe('nextUp', () => {
  it('is today’s first activity, else the first coming one, else nothing', () => {
    const later = create(HomeUpcomingSchema, { id: 'later', isToday: false });
    const today = create(HomeUpcomingSchema, { id: 'today', isToday: true });
    expect(nextUp([later, today])?.id).toBe('today');
    expect(nextUp([later])?.id).toBe('later');
    expect(nextUp([])).toBeUndefined();
  });
});

describe('toneOf', () => {
  it('reads Home’s tone words as the design system’s', () => {
    expect(['alert', 'caution', 'good', 'brand', 'info', 'plain', ''].map(toneOf)).toEqual([
      'danger',
      'warning',
      'success',
      'info',
      'info',
      'neutral',
      'neutral',
    ]);
  });
});
