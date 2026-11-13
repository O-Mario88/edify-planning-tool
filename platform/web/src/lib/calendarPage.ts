/**
 * The Calendar page's answer read back into a month (docs/migration/54).
 * The gateway answers /calendar as the feed reads the existing page: each
 * event tab carries the page's month grid as one panel whose items run in
 * the grid's order — the day's number, then that day's events, the next
 * day's number … — then the month's agenda list and the page's note. A
 * short label that ends one cell is read joined to the next cell's number
 * ("Observance" + "22" arrives as one row), so a row whose value is the day
 * expected next starts that day and its label ends the cell before.
 * Presentation only: every event, link and word is the gateway's.
 */
import type { PageLink, PagePanel, PagePanelItem } from '@/gen/edify/screens/v1/page_pb';

export interface CalendarEvent {
  readonly title: string;
  /** The line under the title: the school, cluster, or a holiday's kind. */
  readonly caption: string;
  /** The event's page ("/my-plan/<id>"), or '' for leave, holidays and events. */
  readonly href: string;
}

export interface CalendarDay {
  readonly day: number;
  readonly events: readonly CalendarEvent[];
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
  readonly days: readonly CalendarDay[];
  /** What the month's agenda says when it has nothing ("No events in November 2026."). */
  readonly empty: string;
  /** The page's note under the grid. */
  readonly note: string;
}

export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Monday-first, as the page draws its grid: 0 for a Monday, 6 for a Sunday. */
export function mondayOffset(year: number, month: number): number {
  return (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
}

function dayNumberOf(item: PagePanelItem, expected: number): { label: string } | null {
  const kind = item.kind;
  if (kind.case === 'text' && kind.value === String(expected)) return { label: '' };
  if (kind.case === 'rows' && kind.value.rows.length === 1 && kind.value.rows[0]?.value === String(expected)) {
    return { label: kind.value.rows[0]?.label ?? '' };
  }
  return null;
}

function eventOfLink(link: PageLink): CalendarEvent {
  return { title: link.text, caption: link.caption, href: link.href };
}

/** A cell's closing label (a holiday's "Public holiday") under its last event that has none. */
function withClosingLabel(events: readonly CalendarEvent[], label: string): readonly CalendarEvent[] {
  const last = events[events.length - 1];
  if (!label || label === 'Today' || !last || last.href || last.caption) return events;
  return [...events.slice(0, -1), { ...last, caption: label }];
}

function eventsOf(items: readonly PagePanelItem[]): readonly CalendarEvent[] {
  let events: readonly CalendarEvent[] = [];
  for (const item of items) {
    const kind = item.kind;
    if (kind.case === 'links') events = [...events, ...kind.value.links.map(eventOfLink)];
    else if (kind.case === 'text' && kind.value) events = [...events, { title: kind.value, caption: '', href: '' }];
  }
  return events;
}

function textsOf(items: readonly PagePanelItem[]): readonly string[] {
  return items.flatMap((item) => (item.kind.case === 'text' && item.kind.value ? [item.kind.value] : []));
}

/**
 * The month in a tab's grid panel, or null when the panel is not a month
 * grid (its days do not run 1 … the month's last day).
 */
export function readMonth(panel: PagePanel, year: number, month: number): CalendarMonth | null {
  const last = daysInMonth(year, month);
  const cells: PagePanelItem[][] = [];
  const closing: string[] = [];
  let badge: CalendarMonth['badge'] = null;
  let current: PagePanelItem[] | null = null;
  for (const item of panel.items) {
    const number = cells.length < last ? dayNumberOf(item, cells.length + 1) : null;
    if (number) {
      closing.push(number.label);
      current = [];
      cells.push(current);
      continue;
    }
    if (current) current.push(item);
    else if (!badge && item.kind.case === 'rows' && item.kind.value.rows.length === 1) {
      const row = item.kind.value.rows[0];
      badge = row ? { label: row.label, value: row.value } : null;
    }
  }
  if (cells.length !== last) return null;
  // After the last day's number: its events, then the agenda list (the last
  // list of links, present whenever the month has an event), then the notes.
  const tail = cells[last - 1] ?? [];
  const agenda = tail.map((item) => item.kind.case).lastIndexOf('links');
  const lastDay = agenda >= 0 ? tail.slice(0, agenda) : [];
  const after = agenda >= 0 ? tail.slice(agenda + 1) : tail;
  const notes = textsOf(after);
  const days = cells.map((items, index) => {
    const own = index === last - 1 ? lastDay : items;
    // A cell's closing label arrives with the next day's number.
    return { day: index + 1, events: withClosingLabel(eventsOf(own), closing[index + 1] ?? '') };
  });
  return {
    year,
    month,
    title: panel.title,
    range: panel.subtitle,
    badge,
    days,
    empty: notes.length > 1 ? notes.slice(0, -1).join(' ') : '',
    note: notes[notes.length - 1] ?? '',
  };
}

/** "All events11" → "All events", "11": the tab's label and its count, read joined. */
export function splitCount(label: string): { label: string; count: string } {
  const match = /^(.*?\D)(\d+)$/.exec(label);
  return match ? { label: (match[1] ?? '').trim(), count: match[2] ?? '' } : { label, count: '' };
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

/** The page's event tabs and the kind each shows (index.html; extended_views._CALENDAR_EVENT_KINDS). */
const EVENT_KINDS: Readonly<Record<string, string>> = {
  'All events': 'all',
  Activities: 'activity',
  Leave: 'leave',
  Holidays: 'holiday',
  'Other events': 'event',
};

export interface EventTab {
  readonly label: string;
  readonly count: string;
  /** The kind the tab shows; '' for a tab the page does not name. */
  readonly kind: string;
}

/**
 * The event tabs with their counts. The answer carries every tab's events
 * unsorted by kind (the page sorts them in the browser by a kind the feed
 * does not read), so only All events is drawn here; the others open the
 * existing page on that kind (`?event_kind=`, which it opens on).
 */
export function eventTabs(labels: readonly string[]): readonly EventTab[] {
  return labels.map((text) => {
    const { label, count } = splitCount(text);
    return { label, count, kind: EVENT_KINDS[label] ?? '' };
  });
}

/** Today's day in this month on Kampala's calendar (timezone.localdate()), or 0. */
export function todayIn(now: Date, year: number, month: number): number {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Africa/Kampala', year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(now);
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return part('year') === year && part('month') === month ? part('day') : 0;
}
