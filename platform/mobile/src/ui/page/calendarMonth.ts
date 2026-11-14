/**
 * The Calendar page's month block (PageBlock.calendar, docs/migration/54.5)
 * read into what the app draws: every day of the month with the open tab's
 * entries, the dots a day shows, each entry's colour (calendar-workspace.css)
 * and the filter changes that move the page to another tab or month. Pure,
 * so it is tested without a device. Every event, link and word is the
 * gateway's; the month's eyebrow and sentences are the page's own panels.
 */
import type { PageCalendar, PageCalendarEvent, PagePanel } from '../../gen/edify/screens/v1/page_pb';
import { MONTHS, WEEKDAYS, daysInMonth, weekday } from '../calendar';

export interface CalendarDayView {
  readonly day: number;
  readonly events: readonly PageCalendarEvent[];
  /** Any of its shown entries is to be rescheduled. */
  readonly dayOff: boolean;
}

export interface CalendarMonthView {
  readonly year: number;
  readonly month: number;
  /** "November 2026" */
  readonly title: string;
  /** The phone month's eyebrow ("Your schedule"), or ''. */
  readonly eyebrow: string;
  /** What the month says with nothing in it ("No events in November 2026."). */
  readonly empty: string;
  readonly days: readonly CalendarDayView[];
  /** Today's day of the month, 0 when today is in another month. */
  readonly today: number;
  /** The open tab ("all" for every kind). */
  readonly kind: string;
  /** Each activity the reader may tick, once however many days it runs. */
  readonly picks: readonly string[];
}

/** The order the page draws a day's dots in (calendar-mobile__dot--<kind>). */
export const DOT_KINDS = ['activity', 'leave', 'holiday', 'event'] as const;

function monthTitle(year: number, month: number): string {
  return `${MONTHS[month - 1] ?? ''} ${year}`;
}

function isoDay(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

/** "No events in November 2026." from the month card's sentences, or the page's own words. */
function emptyOf(panels: readonly PagePanel[], title: string): string {
  const texts = panels.flatMap((panel) => panel.items.flatMap((item) => (item.kind.case === 'text' ? [item.kind.value] : [])));
  return texts.find((text) => text.startsWith('No events in ')) ?? `No events in ${title}.`;
}

/**
 * The month of the calendar block; `panels` are the page's phone month and
 * month card (the segments the block stands in for), for their eyebrow,
 * title and empty sentence.
 */
export function monthOf(calendar: PageCalendar, panels: readonly PagePanel[] = []): CalendarMonthView {
  const { year, month } = calendar;
  const kind = calendar.kind || 'all';
  const isShown = (event: PageCalendarEvent) => kind === 'all' || event.kind === kind;
  const byDate = new Map(calendar.days.map((day) => [day.date, day]));
  const days = Array.from({ length: daysInMonth(year, month) }, (_, index) => {
    const events = (byDate.get(isoDay(year, month, index + 1))?.events ?? []).filter(isShown);
    return { day: index + 1, events, dayOff: events.some((event) => event.dayOff) };
  });
  const phone = panels[0];
  const title = phone?.title || monthTitle(year, month);
  const todayParts = calendar.today.split('-').map(Number);
  const isThisMonth = todayParts[0] === year && todayParts[1] === month;
  const picks = days.flatMap((day) => day.events.map((event) => event.pickId)).filter((id) => id !== '');
  return {
    year,
    month,
    title,
    eyebrow: phone?.subtitle ?? '',
    empty: emptyOf(panels, title),
    days,
    today: isThisMonth ? (todayParts[2] ?? 0) : 0,
    kind,
    picks: [...new Set(picks)],
  };
}

/** Monday-first, as the page draws its grid: 0 for a Monday, 6 for a Sunday. */
export function mondayOffset(year: number, month: number): number {
  return (weekday({ y: year, m: month, d: 1 }) + 6) % 7;
}

/** The kinds a day holds, one dot each, in the page's order. */
export function dotKinds(day: CalendarDayView): readonly string[] {
  return DOT_KINDS.filter((kind) => day.events.some((event) => event.kind === kind));
}

/** The agenda's day heading ("l j F"): "Friday 13 November". */
export function dayHeading(year: number, month: number, day: number): string {
  return `${WEEKDAYS[weekday({ y: year, m: month, d: day })]} ${day} ${MONTHS[month - 1] ?? ''}`;
}

/** The phone month's chosen day: "Friday, November 13". */
export function longDate(year: number, month: number, day: number): string {
  return `${WEEKDAYS[weekday({ y: year, m: month, d: day })]}, ${MONTHS[month - 1] ?? ''} ${day}`;
}

export interface EventTone {
  readonly ink: string;
  readonly fill: string;
  /** The solid left edge of work on a day off, or ''. */
  readonly edge: string;
}

type Tones = Readonly<Record<string, Omit<EventTone, 'edge'>>>;

/**
 * calendar-workspace.css's .calendar-event--<family> colours, with its
 * color-mix() values worked out over the light and dark surfaces.
 */
const LIGHT: Tones = {
  activity: { ink: '#0b3d66', fill: '#ebf5fc' },
  visit: { ink: '#0b3d66', fill: '#ebf5fc' },
  training: { ink: '#065f46', fill: '#ecfdf5' },
  cluster: { ink: '#6d28d9', fill: '#f5f3ff' },
  core: { ink: '#8b401a', fill: '#fdeee7' },
  project: { ink: '#166662', fill: '#f0fdfa' },
  programme: { ink: '#804062', fill: '#fdedf5' },
  leave: { ink: '#92400e', fill: '#fffbeb' },
  holiday: { ink: '#be123c', fill: '#fef2f2' },
  event: { ink: '#664ab5', fill: '#ebe7fa' },
};

const DARK: Tones = {
  activity: { ink: '#8fbfe3', fill: 'rgba(83, 145, 194, 0.18)' },
  visit: { ink: '#8fbfe3', fill: 'rgba(83, 145, 194, 0.18)' },
  training: { ink: '#79ca98', fill: 'rgba(48, 123, 77, 0.22)' },
  cluster: { ink: '#b7a6f4', fill: 'rgba(183, 166, 244, 0.12)' },
  core: { ink: '#f2a46e', fill: 'rgba(234, 88, 12, 0.16)' },
  project: { ink: '#78d5d0', fill: 'rgba(120, 213, 208, 0.12)' },
  programme: { ink: '#f29ac4', fill: 'rgba(236, 72, 153, 0.16)' },
  leave: { ink: '#e7b45a', fill: 'rgba(137, 92, 24, 0.28)' },
  holiday: { ink: '#f18f8a', fill: 'rgba(124, 50, 51, 0.3)' },
  event: { ink: '#c4b5fd', fill: 'rgba(139, 92, 246, 0.16)' },
};

/** The edge of work on a day off (--edify-danger). */
const DAY_OFF_EDGE = { light: '#ef4444', dark: '#f18f8a' } as const;

/** The dot under a grid day for each kind (calendar-mobile__dot--<kind>). */
export const DOT_COLOURS: Readonly<Record<string, { readonly light: string; readonly dark: string }>> = {
  activity: { light: '#0e5da3', dark: '#2f78b7' },
  leave: { light: '#f59e0b', dark: '#e7b45a' },
  holiday: { light: '#ef4444', dark: '#f18f8a' },
  event: { light: '#8b5cf6', dark: '#b7a6f4' },
};

/**
 * An entry's colours: work by its programme family (a family the page does
 * not colour is "activity"), leave, holidays and events by kind; work on a
 * holiday or a leave day in the holiday's colour with a solid edge.
 */
export function eventTone(event: Pick<PageCalendarEvent, 'kind' | 'family' | 'dayOff'>, isDark: boolean): EventTone {
  const tones = isDark ? DARK : LIGHT;
  const fallback = tones.activity as Omit<EventTone, 'edge'>;
  if (event.dayOff) {
    return { ...(tones.holiday ?? fallback), edge: isDark ? DAY_OFF_EDGE.dark : DAY_OFF_EDGE.light };
  }
  return { ...(tones[event.family || event.kind] ?? fallback), edge: '' };
}

/** A change to the page's query, as its filter form sends it (PageBlocksView onFilter). */
export interface CalendarFilter {
  readonly name: string;
  readonly value: string;
  readonly hidden: Readonly<Record<string, string>>;
}

/** An event-type tab: this page on its kind (`?event_kind=`), every kind without one. */
export function kindFilter(hidden: Readonly<Record<string, string>>, kind: string): CalendarFilter {
  return { name: 'event_kind', value: kind === 'all' ? '' : kind, hidden };
}

/** The month before (step -1) or after (step 1), over the year's ends. */
export function monthFilter(hidden: Readonly<Record<string, string>>, year: number, month: number, step: -1 | 1): CalendarFilter {
  const index = year * 12 + (month - 1) + step;
  const next = { year: Math.floor(index / 12), month: (index % 12) + 1 };
  return { name: 'month', value: String(next.month), hidden: { ...hidden, year: String(next.year) } };
}

/** Today: the page without a month or year, which opens on today's month. */
export function todayFilter(hidden: Readonly<Record<string, string>>): CalendarFilter {
  const rest = Object.fromEntries(Object.entries(hidden).filter(([key]) => key !== 'month'));
  return { name: 'month', value: '', hidden: { ...rest, year: '' } };
}
