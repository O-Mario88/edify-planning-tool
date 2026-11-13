import { create } from '@bufbuild/protobuf';

import { PageCalendarSchema, PagePanelSchema } from '../gen/edify/screens/v1/page_pb';
import {
  dayHeading,
  dotKinds,
  eventTone,
  kindFilter,
  longDate,
  monthFilter,
  monthOf,
  mondayOffset,
  todayFilter,
} from '../ui/page/calendarMonth';

/** cceo@'s November 2026 as the gateway answers it, plus a run, leave and a day-off chip. */
const NOVEMBER = create(PageCalendarSchema, {
  year: 2026,
  month: 11,
  today: '2026-11-13',
  kind: 'all',
  kinds: [
    { value: 'all', label: 'All events', count: '5' },
    { value: 'activity', label: 'Activities', count: '4' },
    { value: 'leave', label: 'Leave', count: '1' },
  ],
  days: [
    {
      date: '2026-11-03',
      events: [{ kind: 'activity', family: 'visit', title: 'Donor Visit', meta: 'Kimenyedde', href: '/my-plan/a1', pickId: 'a1' }],
    },
    {
      date: '2026-11-13',
      today: true,
      events: [
        { kind: 'leave', title: 'Annual leave', meta: 'Annual' },
        { kind: 'activity', family: 'training', title: 'Training', meta: 'Day 1 of 2', href: '/my-plan/t1', pickId: 't1' },
      ],
    },
    {
      date: '2026-11-14',
      dayOff: true,
      events: [{ kind: 'activity', family: 'training', title: 'Training', meta: 'Day 2 of 2', pickId: 't1', continued: true, dayOff: true }],
    },
  ],
});

describe('monthOf', () => {
  it('lays out every day of the month with that day’s entries', () => {
    const month = monthOf(NOVEMBER);
    expect(month.days).toHaveLength(30);
    expect(month.days[2]?.events.map((event) => event.title)).toEqual(['Donor Visit']);
    expect(month.days[0]?.events).toEqual([]);
    expect(month.days[13]?.dayOff).toBe(true);
    expect(month.today).toBe(13);
  });

  it('keeps only the open tab’s kind', () => {
    const month = monthOf(create(PageCalendarSchema, { ...NOVEMBER, kind: 'leave' }));
    expect(month.days[12]?.events.map((event) => event.kind)).toEqual(['leave']);
    expect(month.days[2]?.events).toEqual([]);
    expect(month.kind).toBe('leave');
  });

  it('counts a run over several days as one tick', () => {
    expect(monthOf(NOVEMBER).picks).toEqual(['a1', 't1']);
  });

  it('reads the phone month’s eyebrow and title, and the card’s empty sentence', () => {
    const phone = create(PagePanelSchema, { title: 'November 2026', subtitle: 'Your schedule' });
    const card = create(PagePanelSchema, {
      title: 'November 2026',
      items: [{ kind: { case: 'text', value: 'No events in November 2026.' } }, { kind: { case: 'text', value: 'A note.' } }],
    });
    const month = monthOf(NOVEMBER, [phone, card]);
    expect(month.eyebrow).toBe('Your schedule');
    expect(month.title).toBe('November 2026');
    expect(month.empty).toBe('No events in November 2026.');
  });

  it('names the month itself when the page has no panels', () => {
    const month = monthOf(NOVEMBER);
    expect(month.title).toBe('November 2026');
    expect(month.empty).toBe('No events in November 2026.');
  });

  it('has no today in another month', () => {
    expect(monthOf(create(PageCalendarSchema, { ...NOVEMBER, today: '' })).today).toBe(0);
  });
});

describe('the grid', () => {
  it('starts weeks on Monday, as the page draws them', () => {
    expect(mondayOffset(2026, 11)).toBe(6); // 1 November 2026 is a Sunday
    expect(mondayOffset(2026, 6)).toBe(0); // 1 June 2026 is a Monday
  });

  it('puts one dot per kind a day holds, in the page’s order', () => {
    const month = monthOf(NOVEMBER);
    expect(dotKinds(month.days[12]!)).toEqual(['activity', 'leave']);
    expect(dotKinds(month.days[0]!)).toEqual([]);
  });

  it('heads a day as the agenda does', () => {
    expect(dayHeading(2026, 11, 13)).toBe('Friday 13 November');
  });

  it('names the chosen day as the phone month does', () => {
    expect(longDate(2026, 11, 13)).toBe('Friday, November 13');
  });
});

describe('eventTone', () => {
  it('colours work by its family and other entries by kind', () => {
    expect(eventTone({ kind: 'activity', family: 'training', dayOff: false }, false).ink).toBe('#065f46');
    expect(eventTone({ kind: 'leave', family: '', dayOff: false }, false).ink).toBe('#92400e');
    expect(eventTone({ kind: 'activity', family: 'unknown', dayOff: false }, false)).toEqual(
      eventTone({ kind: 'activity', family: 'activity', dayOff: false }, false),
    );
  });

  it('draws work on a day off in the holiday’s colour with a solid edge', () => {
    const tone = eventTone({ kind: 'activity', family: 'visit', dayOff: true }, false);
    expect(tone.fill).toBe(eventTone({ kind: 'holiday', family: '', dayOff: false }, false).fill);
    expect(tone.edge).toBe('#ef4444');
  });
});

describe('moving the calendar', () => {
  const hidden = { year: '2026', month: '11', event_kind: '', person: '7' };

  it('opens a tab on its kind, every kind without one', () => {
    expect(kindFilter(hidden, 'leave')).toEqual({ name: 'event_kind', value: 'leave', hidden });
    expect(kindFilter(hidden, 'all')).toEqual({ name: 'event_kind', value: '', hidden });
  });

  it('steps months over the year’s ends', () => {
    expect(monthFilter(hidden, 2026, 12, 1)).toEqual({ name: 'month', value: '1', hidden: { ...hidden, year: '2027' } });
    expect(monthFilter(hidden, 2026, 1, -1)).toEqual({ name: 'month', value: '12', hidden: { ...hidden, year: '2025' } });
    expect(monthFilter(hidden, 2026, 11, -1)).toEqual({ name: 'month', value: '10', hidden });
  });

  it('goes back to today’s month by dropping the month', () => {
    expect(todayFilter(hidden)).toEqual({ name: 'month', value: '', hidden: { event_kind: '', person: '7', year: '' } });
  });
});
