/**
 * The Edify calendar's arithmetic (static/js/date-picker.js): a saved date
 * is a calendar day, never an instant — read and written as its parts, so a
 * reader west of UTC is never shown the previous day. Pure, so it is tested
 * without a device.
 */

export interface Day {
  readonly y: number;
  readonly m: number;
  readonly d: number;
}

export interface Month {
  readonly y: number;
  readonly m: number;
}

export const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
] as const;
export const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'] as const;

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
/** Six weeks: every month fits, and the grid never changes height. */
const CELLS = 42;

export function daysInMonth(y: number, m: number): number {
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

/** 0 for Sunday … 6 for Saturday. */
export function weekday(day: Day): number {
  return new Date(Date.UTC(day.y, day.m - 1, day.d)).getUTCDay();
}

export function parseIso(value: string): Day | null {
  const found = ISO.exec(value);
  if (!found) {
    return null;
  }
  const day = { y: Number(found[1]), m: Number(found[2]), d: Number(found[3]) };
  if (day.m < 1 || day.m > 12 || day.d < 1 || day.d > daysInMonth(day.y, day.m)) {
    return null;
  }
  return day;
}

export function toIso(day: Day): string {
  return `${day.y}-${String(day.m).padStart(2, '0')}-${String(day.d).padStart(2, '0')}`;
}

export function fromDate(date: Date): Day {
  return { y: date.getFullYear(), m: date.getMonth() + 1, d: date.getDate() };
}

/** "Nov 12, 2026", as the web's field shows a date. */
export function shortLabel(day: Day): string {
  return `${MONTHS[day.m - 1].slice(0, 3)} ${day.d}, ${day.y}`;
}

/** "Thursday, November 12, 2026", for a screen reader. */
export function longLabel(day: Day): string {
  return `${WEEKDAYS[weekday(day)]}, ${MONTHS[day.m - 1]} ${day.d}, ${day.y}`;
}

export function compare(a: Day, b: Day): number {
  return a.y - b.y || a.m - b.m || a.d - b.d;
}

/** A month's grid from Sunday: its days, blank before the first and after the last. */
export function monthCells(y: number, m: number): (Day | null)[] {
  const cells: (Day | null)[] = Array.from({ length: weekday({ y, m, d: 1 }) }, () => null);
  for (let d = 1; d <= daysInMonth(y, m); d++) {
    cells.push({ y, m, d });
  }
  while (cells.length < CELLS) {
    cells.push(null);
  }
  return cells;
}

export function addMonths(month: Month, step: number): Month {
  const index = month.y * 12 + (month.m - 1) + step;
  return { y: Math.floor(index / 12), m: (index % 12) + 1 };
}

/** Whether a day may be picked: on or after `min`, on or before `max` (ISO, '' for none). */
export function isWithin(day: Day, min: string, max: string): boolean {
  const low = parseIso(min);
  const high = parseIso(max);
  return (!low || compare(day, low) >= 0) && (!high || compare(day, high) <= 0);
}

/** The month the calendar opens on: the field's own date's, else today's kept inside min and max. */
export function openingMonth(value: string, min: string, max: string, today: Day): Month {
  const own = parseIso(value);
  if (own) {
    return { y: own.y, m: own.m };
  }
  const low = parseIso(min);
  const high = parseIso(max);
  let day = today;
  if (low && compare(day, low) < 0) {
    day = low;
  }
  if (high && compare(day, high) > 0) {
    day = high;
  }
  return { y: day.y, m: day.m };
}
