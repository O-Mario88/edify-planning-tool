/**
 * The Calendar page's answer read into a month (docs/migration/54). The
 * gateway answers /calendar with a month block (PageCalendar): each day of
 * the month with entries, each entry's kind, colour family, words, link,
 * tick box, multi-day run and day-off mark, and the event-type tabs with
 * their keys and counts. The month card's toolbar words (title, range, date
 * badge, empty sentence, note) are the grid panel's own fields.
 * Presentation only: every event, link and word is the gateway's.
 */
import type { PageCalendar, PageCalendarEvent, PagePanel } from '@/gen/edify/screens/v1/page_pb';

export interface CalendarEvent {
  /** "activity", "leave", "holiday" or "event". */
  readonly kind: string;
  /** An activity's colour family ("visit", "training", "cluster", "core", "project", "programme", "activity"). */
  readonly family: string;
  readonly title: string;
  /** The line under the title: the place, the run's day, a holiday's kind. */
  readonly caption: string;
  /** The event's page ("/my-plan/<id>"), or '' for leave, holidays and events. */
  readonly href: string;
  /** The activity its tick box ticks, or ''. */
  readonly pickId: string;
  /** A later day of a run over several days. */
  readonly continued: boolean;
  /** Planned on a public holiday or its owner's leave: to reschedule. */
  readonly dayOff: boolean;
}

export interface CalendarDay {
  readonly day: number;
  readonly events: readonly CalendarEvent[];
  readonly dayOff: boolean;
}

export interface EventTab {
  /** The kind the tab shows ("all", "activity" …). */
  readonly kind: string;
  readonly label: string;
  readonly count: string;
}

export interface CalendarMonth {
  readonly year: number;
  readonly month: number;
  /** "November 2026" */
  readonly title: string;
  /** "November 1, 2026 – November 30, 2026" */
  readonly range: string;
  /** The date badge: "NOV" over "01". */
  readonly badge: { readonly label: string; readonly value: string } | null;
  /** Every day of the month, with the open tab's events. */
  readonly days: readonly CalendarDay[];
  /** What the month's agenda says when it has nothing ("No events in November 2026."). */
  readonly empty: string;
  /** The page's note under the grid. */
  readonly note: string;
  readonly tabs: readonly EventTab[];
  /** The open tab's kind ("all" for every kind). */
  readonly kind: string;
  /** Any entry is ticked for the page's bar. */
  readonly ticks: boolean;
}

export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Monday-first, as the page draws its grid: 0 for a Monday, 6 for a Sunday. */
export function mondayOffset(year: number, month: number): number {
  return (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
}

/** A month's cells, blanks included, cut into weeks of seven: each the
 *  grid's row, so a screen reader reads the days as a grid (2026-11-20, axe:
 *  a gridcell needs a row). */
export function weeksOf<T>(cells: readonly T[]): T[][] {
  const weeks: T[][] = [];
  for (let start = 0; start < cells.length; start += 7) weeks.push(cells.slice(start, start + 7));
  return weeks;
}

function eventOf(event: PageCalendarEvent): CalendarEvent {
  return {
    kind: event.kind,
    family: event.family,
    title: event.title,
    caption: event.meta,
    href: event.href,
    pickId: event.pickId,
    continued: event.continued,
    dayOff: event.dayOff,
  };
}

/** "No events in November 2026." / the note: the grid panel's sentences. */
function sentencesOf(panel: PagePanel | undefined): { empty: string; note: string } {
  const texts = (panel?.items ?? []).flatMap((item) => (item.kind.case === 'text' && item.kind.value ? [item.kind.value] : []));
  return { empty: texts.find((text) => text.startsWith('No events in ')) ?? '', note: texts.at(-1) ?? '' };
}

function badgeOf(panel: PagePanel | undefined): CalendarMonth['badge'] {
  const first = panel?.items[0];
  const row = first?.kind.case === 'rows' && first.kind.value.rows.length === 1 ? first.kind.value.rows[0] : undefined;
  return row ? { label: row.label, value: row.value } : null;
}

/**
 * The month of the answer's calendar block, the open tab's entries on each
 * of its days; `panel` is the month card's own panel (its title, range,
 * badge and sentences).
 */
export function monthOf(calendar: PageCalendar, panel: PagePanel | undefined): CalendarMonth {
  const { year, month, kind } = calendar;
  const byDate = new Map(calendar.days.map((day) => [day.date, day]));
  const shown = (event: PageCalendarEvent) => kind === 'all' || !kind || event.kind === kind;
  const days = Array.from({ length: daysInMonth(year, month) }, (_, index) => {
    const date = `${year}-${String(month).padStart(2, '0')}-${String(index + 1).padStart(2, '0')}`;
    const events = (byDate.get(date)?.events ?? []).filter(shown).map(eventOf);
    return { day: index + 1, events, dayOff: events.some((event) => event.dayOff) };
  });
  const { empty, note } = sentencesOf(panel);
  return {
    year,
    month,
    title: panel?.title ?? '',
    range: panel?.subtitle ?? '',
    badge: badgeOf(panel),
    days,
    empty,
    note,
    tabs: calendar.kinds.map((chip) => ({ kind: chip.value, label: chip.label, count: chip.count })),
    kind: kind || 'all',
    ticks: calendar.days.some((day) => day.events.some((event) => event.pickId)),
  };
}

/** The same calendar on another event-type tab (`?event_kind=`, dropped for every kind). */
export function kindLink(query: Readonly<Record<string, string>>, kind: string): string {
  const rest = Object.fromEntries(Object.entries(query).filter(([key]) => key !== 'event_kind'));
  const params = new URLSearchParams(kind === 'all' ? rest : { ...rest, event_kind: kind }).toString();
  return params ? `/calendar?${params}` : '/calendar';
}

export interface PeopleTab {
  readonly label: string;
  readonly count: string;
  readonly href: string;
  readonly active: boolean;
}

function personOf(href: string): string {
  return new URL(href, 'http://web.invalid').searchParams.get('person') ?? '';
}

/**
 * The people strips (a Lead's officers; the Director's teams and, once one
 * is open, its members) arrive as one list of links, each count in its
 * caption; the second strip starts where a link repeats an earlier one
 * (its Lead). The open tab is the reader's `person`; a team strip's open
 * tab is the team whose Lead heads the open member strip.
 */
export function peopleStrips(panel: PagePanel, person: string): readonly (readonly PeopleTab[])[] | null {
  const [item, ...rest] = panel.items;
  if (panel.title || rest.length || item?.kind.case !== 'links') return null;
  const links = item.kind.value.links;
  if (!links.length || !links.every((link) => link.href.startsWith('/calendar?') && /^\d+$/.test(link.caption))) return null;
  const split = links.findIndex((link, index) => links.slice(0, index).some((earlier) => earlier.href === link.href));
  const strips = split > 0 ? [links.slice(0, split), links.slice(split)] : [links];
  const lead = strips[1]?.[0] ? personOf(strips[1][0].href) : '';
  return strips.map((strip, index) => {
    const exact = strip.some((link) => personOf(link.href) === person);
    const open = exact || index > 0 ? person : lead;
    return strip.map((link) => ({ label: link.text, count: link.caption, href: link.href, active: personOf(link.href) === open }));
  });
}

/** The page's own month links: the month before, this month, the month after. */
export function monthLinks(query: Readonly<Record<string, string>>, year: number, month: number): { previous: string; today: string; next: string } {
  const at = (y: number, m: number) => {
    const params = new URLSearchParams({ ...query, year: String(y), month: String(m) });
    return `/calendar?${params.toString()}`;
  };
  const rest = Object.fromEntries(Object.entries(query).filter(([key]) => key !== 'year' && key !== 'month'));
  const today = new URLSearchParams(rest).toString();
  return {
    previous: month === 1 ? at(year - 1, 12) : at(year, month - 1),
    today: today ? `/calendar?${today}` : '/calendar',
    next: month === 12 ? at(year + 1, 1) : at(year, month + 1),
  };
}

/** Month or Agenda: the same query with `view` set (or dropped for the month). */
export function viewLink(query: Readonly<Record<string, string>>, view: 'month' | 'agenda'): string {
  const rest = Object.fromEntries(Object.entries(query).filter(([key]) => key !== 'view'));
  const params = new URLSearchParams(view === 'agenda' ? { ...rest, view } : rest).toString();
  return params ? `/calendar?${params}` : '/calendar';
}

/** Today's day in this month on Kampala's calendar (timezone.localdate()), or 0. */
export function todayIn(now: Date, year: number, month: number): number {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Africa/Kampala', year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(now);
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return part('year') === year && part('month') === month ? part('day') : 0;
}
