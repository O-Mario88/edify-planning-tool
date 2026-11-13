import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { PagePanelSchema } from '@/gen/edify/screens/v1/page_pb';

import { daysInMonth, eventTabs, mondayOffset, monthLinks, peopleStrips, readMonth, splitCount, todayIn, viewLink } from './calendarPage';

type Item = NonNullable<MessageInitShape<typeof PagePanelSchema>['items']>[number];

const text = (value: string): Item => ({ kind: { case: 'text', value } });
const row = (label: string, value: string): Item => ({ kind: { case: 'rows', value: { rows: [{ label, value }] } } });
const links = (...items: { text: string; href?: string; caption?: string }[]): Item => ({ kind: { case: 'links', value: { links: items } } });
const panel = (items: Item[], title = 'February 2026', subtitle = 'February 1, 2026 – February 28, 2026') => create(PagePanelSchema, { title, subtitle, items });

/** A month's days as the gateway reads them: day 1 joined to the last weekday heading. */
function days(last: number, between: Readonly<Record<number, Item[]>> = {}, joined: Readonly<Record<number, string>> = {}): Item[] {
  const items: Item[] = [];
  for (let day = 1; day <= last; day += 1) {
    const label = day === 1 ? 'Sun' : joined[day];
    items.push(label ? row(label, String(day)) : text(String(day)));
    items.push(...(between[day] ?? []));
  }
  return items;
}

const NOTE = 'Leave, holidays, and organization events are overlays and never count as activities.';

describe('readMonth', () => {
  it('puts each event under the day number before it, with its school', () => {
    const visit = { text: 'Donor Visit', href: '/my-plan/a1', caption: 'Kimenyedde Primary' };
    const items = [row('FEB', '01'), text('Select all'), text('Today'), text('Mon'), ...days(28, { 3: [links(visit)] }), links({ text: 'Donor VisitKimenyedde Primary', href: '/my-plan/a1' }), text(NOTE)];
    const month = readMonth(panel(items), 2026, 2);
    expect(month?.badge).toEqual({ label: 'FEB', value: '01' });
    expect(month?.days).toHaveLength(28);
    expect(month?.days[2]?.events).toEqual([{ title: 'Donor Visit', caption: 'Kimenyedde Primary', href: '/my-plan/a1' }]);
    expect(month?.days.filter((day) => day.events.length)).toHaveLength(1);
    expect(month?.note).toBe(NOTE);
    expect(month?.empty).toBe('');
  });

  it('gives a holiday the label that arrives joined to the next day number', () => {
    const items = [...days(28, { 16: [text('Archbishop Janani Luwum Day')] }, { 17: 'Public holiday' }), links({ text: 'Monday 16 February …' }), text(NOTE)];
    const month = readMonth(panel(items), 2026, 2);
    expect(month?.days[15]?.events).toEqual([{ title: 'Archbishop Janani Luwum Day', caption: 'Public holiday', href: '' }]);
    expect(month?.days[16]?.events).toEqual([]);
  });

  it('ignores the Today label that ends today’s cell', () => {
    const month = readMonth(panel([...days(28, {}, { 14: 'Today' }), text(NOTE)]), 2026, 2);
    expect(month?.days.every((day) => day.events.length === 0)).toBe(true);
  });

  it('tells the last day’s events from the agenda list after them', () => {
    const last = { text: 'School Visit', href: '/my-plan/z', caption: 'Cluster E' };
    const items = [...days(28, { 28: [links(last), links({ text: 'School VisitCluster E', href: '/my-plan/z' })] }), text(NOTE)];
    const month = readMonth(panel(items), 2026, 2);
    expect(month?.days[27]?.events).toEqual([{ title: 'School Visit', caption: 'Cluster E', href: '/my-plan/z' }]);
  });

  it('keeps an empty month’s sentence apart from the note', () => {
    const month = readMonth(panel([...days(28), text('No events in February 2026.'), text(NOTE)]), 2026, 2);
    expect(month?.empty).toBe('No events in February 2026.');
    expect(month?.note).toBe(NOTE);
    expect(month?.days.every((day) => day.events.length === 0)).toBe(true);
  });

  it('is not a month when the days do not run to the month’s end', () => {
    expect(readMonth(panel([...days(27), text(NOTE)]), 2026, 2)).toBeNull();
    expect(readMonth(panel([links({ text: 'Donor VisitKimenyedde', href: '/my-plan/a' })]), 2026, 2)).toBeNull();
  });
});

describe('month arithmetic', () => {
  it('counts days and Monday-first offsets', () => {
    expect(daysInMonth(2026, 2)).toBe(28);
    expect(daysInMonth(2028, 2)).toBe(29);
    expect(mondayOffset(2026, 11)).toBe(6);
    expect(mondayOffset(2026, 12)).toBe(1);
  });
});

describe('splitCount', () => {
  it('reads a tab’s label and its joined count', () => {
    expect(splitCount('All events11')).toEqual({ label: 'All events', count: '11' });
    expect(splitCount('Leave0')).toEqual({ label: 'Leave', count: '0' });
    expect(splitCount('Leave')).toEqual({ label: 'Leave', count: '' });
  });
});

describe('peopleStrips', () => {
  const at = (person = '') => `/calendar?year=2026&month=11${person ? `&person=${person}` : ''}`;
  const teams = [
    { text: 'My calendar', href: at(), caption: '0' },
    { text: "Program Lead 1's team", href: at('pl1'), caption: '11' },
    { text: "Program Lead 2's team", href: at('pl2'), caption: '0' },
  ];
  const members = [
    { text: 'Program Lead 1', href: at('pl1'), caption: '0' },
    { text: 'Paul N.', href: at('paul'), caption: '11' },
  ];

  it('marks the reader’s own calendar open when no one is asked for', () => {
    const strips = peopleStrips(panel([links(...teams)], '', ''), '');
    expect(strips?.map((strip) => strip.filter((tab) => tab.active).map((tab) => tab.label))).toEqual([['My calendar']]);
  });

  it('splits the member strip where a link repeats and opens the member’s team', () => {
    const strips = peopleStrips(panel([links(...teams, ...members)], '', ''), 'paul');
    expect(strips).toHaveLength(2);
    expect(strips?.[0]?.find((tab) => tab.active)?.label).toBe("Program Lead 1's team");
    expect(strips?.[1]?.find((tab) => tab.active)?.label).toBe('Paul N.');
    expect(strips?.[1]?.[1]?.count).toBe('11');
  });

  it('is not a strip for any other panel', () => {
    expect(peopleStrips(panel([{ kind: { case: 'heading', value: 'Add other event' } }], 'Add an organization event', ''), '')).toBeNull();
    expect(peopleStrips(panel([links({ text: 'Open', href: '/my-plan/a', caption: '1' })], '', ''), '')).toBeNull();
  });
});

describe('month and view links', () => {
  it('steps across the year and keeps the page’s other choices', () => {
    const query = { year: '2026', month: '12', status: 'scheduled' };
    expect(monthLinks(query, 2026, 12)).toEqual({
      previous: '/calendar?year=2026&month=11&status=scheduled',
      today: '/calendar?status=scheduled',
      next: '/calendar?year=2027&month=1&status=scheduled',
    });
    expect(monthLinks({}, 2026, 1).previous).toBe('/calendar?year=2025&month=12');
  });

  it('sets or drops the agenda view', () => {
    expect(viewLink({ month: '11' }, 'agenda')).toBe('/calendar?month=11&view=agenda');
    expect(viewLink({ view: 'agenda' }, 'month')).toBe('/calendar');
  });
});

describe('eventTabs and todayIn', () => {
  it('names each tab’s kind', () => {
    expect(eventTabs(['All events11', 'Holidays0', 'Something2'])).toEqual([
      { label: 'All events', count: '11', kind: 'all' },
      { label: 'Holidays', count: '0', kind: 'holiday' },
      { label: 'Something', count: '2', kind: '' },
    ]);
  });

  it('reads today on Kampala’s calendar', () => {
    // 22:30 UTC on 13 November is already the 14th in Kampala.
    expect(todayIn(new Date(Date.UTC(2026, 10, 13, 22, 30)), 2026, 11)).toBe(14);
    expect(todayIn(new Date(Date.UTC(2026, 10, 13, 22, 30)), 2026, 12)).toBe(0);
  });
});
