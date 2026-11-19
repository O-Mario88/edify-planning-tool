import { create } from '@bufbuild/protobuf';

import { HomePriorityRowSchema, HomeUpcomingSchema } from '../gen/edify/screens/v1/home_pb';
import {
  allClear,
  countedFigures,
  nextUp,
  redesignedToday,
  todosLinkLabel,
  toneOf,
  waitingRows,
} from '../ds/todayView';

const row = (key: string, over: Partial<{ count: number; statusTone: string }> = {}) =>
  create(HomePriorityRowSchema, { key, title: key, ...over });

describe('the redesigned Today chooses what the web Today chooses', () => {
  test('a row that only reports nothing to do is left out, in Home’s order', () => {
    const rows = [
      row('overdue', { count: 8, statusTone: 'alert' }),
      row('unclustered', { count: 0, statusTone: 'good' }),
      row('task', { count: 0, statusTone: 'info' }),
      row('none-visited', { count: 3, statusTone: 'good' }),
    ];
    expect(waitingRows(rows).map((r) => r.key)).toEqual(['overdue', 'task', 'none-visited']);
    expect(allClear(rows[1]!)).toBe(true);
  });

  test('figures are whole numbers above nought, and none still loading', () => {
    const cards = ['4', '0', '1,204', 'No data', '', '0,000', '12%'].map((value, i) => ({ key: `k${i}`, value }));
    expect(countedFigures(cards).map((c) => c.value)).toEqual(['4', '1,204']);
    expect(countedFigures([{ key: 'todo', value: '9', loading: true }])).toEqual([]);
  });

  test('next up is today’s first activity, else the first coming one, else nothing', () => {
    const later = create(HomeUpcomingSchema, { id: 'later', isToday: false });
    const today = create(HomeUpcomingSchema, { id: 'today', isToday: true });
    expect(nextUp([later, today])?.id).toBe('today');
    expect(nextUp([later])?.id).toBe('later');
    expect(nextUp([])).toBeUndefined();
  });

  test('Home’s tone words read as the design system’s', () => {
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

  test('the To-Dos link names the total once it is known', () => {
    expect(todosLinkLabel(9)).toBe('All 9 To-Dos');
    expect(todosLinkLabel(null)).toBe('All To-Dos');
    expect(todosLinkLabel(0)).toBe('All To-Dos');
  });

  test('only the CCEO has the redesigned Today so far, as on the web', () => {
    expect(redesignedToday('CCEO')).toBe(true);
    for (const role of ['ProgramLead', 'CountryDirector', 'ImpactAssessment', 'Admin', '']) {
      expect(redesignedToday(role)).toBe(false);
    }
  });
});
