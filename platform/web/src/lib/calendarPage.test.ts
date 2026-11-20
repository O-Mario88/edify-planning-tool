import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { PageCalendarSchema, PagePanelSchema } from '@/gen/edify/screens/v1/page_pb';

import { daysInMonth, kindLink, mondayOffset, monthLinks, monthOf, peopleStrips, todayIn, viewLink, weeksOf } from './calendarPage';

type Item = NonNullable<MessageInitShape<typeof PagePanelSchema>['items']>[number];

const text = (value: string): Item => ({ kind: { case: 'text', value } });
const row = (label: string, value: string): Item => ({ kind: { case: 'rows', value: { rows: [{ label, value }] } } });
const links = (...items: { text: string; href?: string; caption?: string }[]): Item => ({ kind: { case: 'links', value: { links: items } } });
const panel = (items: Item[], title = 'February 2026', subtitle = 'February 1, 2026 – February 28, 2026') => create(PagePanelSchema, { title, subtitle, items });

const NOTE = 'Leave, holidays, and organization events are overlays and never count as activities.';

const CALENDAR = create(PageCalendarSchema, {
  year: 2026,
  month: 2,
  today: '2026-02-03',
  kind: 'all',
  kinds: [
    { value: 'all', label: 'All events', count: '4' },
    { value: 'activity', label: 'Activities', count: '3' },
    { value: 'holiday', label: 'Holidays', count: '1' },
  ],
  days: [
    {
      date: '2026-02-03',
      today: true,
      events: [
        { kind: 'holiday', title: 'Janani Luwum Day', meta: 'Public holiday' },
        { kind: 'activity', family: 'core', title: 'Core Visit', meta: 'Reschedule: public holiday · Kimenyedde · 3–4 February 2026', href: '/my-plan/a1', pickId: 'a1', dayOff: true },
      ],
    },
    { date: '2026-02-04', events: [{ kind: 'activity', family: 'core', title: 'Core Visit', meta: 'Kimenyedde · Day 2 of 2', href: '/my-plan/a1', pickId: 'a1', continued: true }] },
  ],
});

describe('monthOf', () => {
  it('puts each entry on its day with its kind, family, tick and marks', () => {
    const month = monthOf(CALENDAR, panel([row('FEB', '01'), text('No events in February 2026.'), text(NOTE)]));
    expect(month.days).toHaveLength(28);
    expect(month.days[2]?.dayOff).toBe(true);
    expect(month.days[2]?.events.map((event) => [event.kind, event.family, event.pickId, event.dayOff])).toEqual([
      ['holiday', '', '', false],
      ['activity', 'core', 'a1', true],
    ]);
    expect(month.days[3]?.events[0]).toMatchObject({ title: 'Core Visit', caption: 'Kimenyedde · Day 2 of 2', continued: true, dayOff: false });
    expect(month.days[3]?.dayOff).toBe(false);
    expect(month.days[0]?.events).toEqual([]);
    expect(month).toMatchObject({ title: 'February 2026', badge: { label: 'FEB', value: '01' }, empty: 'No events in February 2026.', note: NOTE, kind: 'all', ticks: true });
    expect(month.tabs[1]).toEqual({ kind: 'activity', label: 'Activities', count: '3' });
  });

  it('keeps only the open tab’s kind', () => {
    const month = monthOf(create(PageCalendarSchema, { ...CALENDAR, kind: 'holiday' }), undefined);
    expect(month.days[2]?.events.map((event) => event.kind)).toEqual(['holiday']);
    expect(month.days[2]?.dayOff).toBe(false);
    expect(month.days[3]?.events).toEqual([]);
    expect(month.ticks).toBe(true);
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

describe('kindLink and todayIn', () => {
  it('opens the calendar on a kind, dropping it for every kind', () => {
    expect(kindLink({ year: '2026', month: '2', event_kind: 'leave' }, 'holiday')).toBe('/calendar?year=2026&month=2&event_kind=holiday');
    expect(kindLink({ event_kind: 'leave' }, 'all')).toBe('/calendar');
  });

  it('reads today on Kampala’s calendar', () => {
    // 22:30 UTC on 13 November is already the 14th in Kampala.
    expect(todayIn(new Date(Date.UTC(2026, 10, 13, 22, 30)), 2026, 11)).toBe(14);
    expect(todayIn(new Date(Date.UTC(2026, 10, 13, 22, 30)), 2026, 12)).toBe(0);
  });
});

describe('a month cut into weeks', () => {
  it('is rows of seven, the last one short when the month ends mid-week', () => {
    expect(weeksOf([1, 2, 3, 4, 5, 6, 7, 8, 9])).toEqual([[1, 2, 3, 4, 5, 6, 7], [8, 9]]);
    expect(weeksOf([])).toEqual([]);
  });
});
