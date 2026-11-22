/**
 * Pure, timezone-safe YYYY-MM-DD calendar arithmetic and Uganda FY / scheduling
 * rules for the platform-wide EdifyDatePicker (Sections 10 & 11).
 *
 * Every operation uses integer (year, month, day) tuples so UTC offsets never
 * shift a selected date by +/- 1 day.
 */

export interface IsoParts {
  y: number;
  m: number; // 1..12
  d: number; // 1..31
}

export interface HolidayRule {
  date: string; // YYYY-MM-DD
  name: string;
}

export interface DatePolicy {
  /** 'planning' disables Sundays, public holidays, approved leave, and blackouts (Saturdays remain available). */
  mode?: 'planning' | 'free';
  min?: string;
  max?: string;
  holidays?: readonly HolidayRule[];
  approvedLeaveDates?: readonly string[];
  blackoutDates?: readonly string[];
  conflictDates?: readonly string[];
}

export interface DayCell {
  iso: string;
  day: number;
  inMonth: boolean;
  weekday: number; // 0=Sun..6=Sat
}

export const MONTHS_FULL = [
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

export const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const;
export const WEEKDAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const;

const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function daysInMonth(y: number, m: number): number {
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

export function parseIso(raw: string | undefined | null): IsoParts | null {
  if (!raw) return null;
  const m = ISO_RE.exec(raw.trim());
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > daysInMonth(y, mo)) return null;
  return { y, m: mo, d };
}

export function toIso(p: IsoParts): string {
  return `${String(p.y).padStart(4, '0')}-${String(p.m).padStart(2, '0')}-${String(p.d).padStart(2, '0')}`;
}

export function weekdayOf(p: IsoParts): number {
  return new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay();
}

export function addDays(iso: string, delta: number): string {
  const p = parseIso(iso);
  if (!p) return iso;
  const dt = new Date(Date.UTC(p.y, p.m - 1, p.d + delta));
  return toIso({ y: dt.getUTCFullYear(), m: dt.getUTCMonth() + 1, d: dt.getUTCDate() });
}

export function addMonths(y: number, m: number, delta: number): { y: number; m: number } {
  const total = y * 12 + (m - 1) + delta;
  return { y: Math.floor(total / 12), m: ((total % 12) + 12) % 12 + 1 };
}

export function compareIso(a: string, b: string): number {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/** Today in Africa/Kampala (EAT, UTC+3) without local browser UTC drift. */
export function kampalaTodayIso(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Africa/Kampala',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const y = parts.find((p) => p.type === 'year')?.value ?? '2026';
  const m = parts.find((p) => p.type === 'month')?.value ?? '01';
  const d = parts.find((p) => p.type === 'day')?.value ?? '01';
  return `${y}-${m}-${d}`;
}

/** Human-readable display e.g. "Mon, 23 Nov 2026" or "Nov 23, 2026". */
export function formatDisplayDate(iso: string, style: 'medium' | 'weekday' = 'medium'): string {
  const p = parseIso(iso);
  if (!p) return '';
  if (style === 'weekday') {
    return `${WEEKDAYS_SHORT[weekdayOf(p)]}, ${String(p.d).padStart(2, '0')} ${MONTHS_SHORT[p.m - 1]} ${p.y}`;
  }
  return `${MONTHS_SHORT[p.m - 1]} ${p.d}, ${p.y}`;
}

/**
 * Uganda financial year boundaries: Oct 1 – Sep 30.
 * Example: 2026-10-01 .. 2027-09-30 => FY2027.
 */
export function ugandaFiscalYear(iso: string): { fy: string; start: string; end: string } {
  const p = parseIso(iso) ?? parseIso(kampalaTodayIso())!;
  const fyYear = p.m >= 10 ? p.y + 1 : p.y;
  return {
    fy: `FY${fyYear}`,
    start: `${fyYear - 1}-10-01`,
    end: `${fyYear}-09-30`,
  };
}

/** Builds a 42-cell (6-week) calendar grid including leading/trailing outside-month days. */
export function buildMonthGrid(y: number, m: number): DayCell[] {
  const firstDow = weekdayOf({ y, m, d: 1 });
  const dim = daysInMonth(y, m);
  const prev = addMonths(y, m, -1);
  const prevDim = daysInMonth(prev.y, prev.m);
  const next = addMonths(y, m, 1);

  const cells: DayCell[] = [];
  for (let i = firstDow - 1; i >= 0; i--) {
    const d = prevDim - i;
    const parts = { y: prev.y, m: prev.m, d };
    cells.push({ iso: toIso(parts), day: d, inMonth: false, weekday: weekdayOf(parts) });
  }
  for (let d = 1; d <= dim; d++) {
    const parts = { y, m, d };
    cells.push({ iso: toIso(parts), day: d, inMonth: true, weekday: weekdayOf(parts) });
  }
  let nextDay = 1;
  while (cells.length < 42) {
    const parts = { y: next.y, m: next.m, d: nextDay++ };
    cells.push({ iso: toIso(parts), day: parts.d, inMonth: false, weekday: weekdayOf(parts) });
  }
  return cells;
}

export interface DayAvailability {
  disabled: boolean;
  reason: string;
  badge?: 'holiday' | 'leave' | 'blackout' | 'conflict';
}

/**
 * Evaluates scheduling availability for one ISO day.
 * - Planning mode: Sundays unavailable, Saturdays available, public holidays /
 *   approved leave / blackout dates unavailable.
 * - Free mode: Only min/max range enforced (historical, financial, or leave-entry dates).
 */
export function evaluateDayAvailability(iso: string, policy?: DatePolicy): DayAvailability {
  const p = parseIso(iso);
  if (!p) return { disabled: true, reason: 'Invalid date' };
  if (policy?.min && compareIso(iso, policy.min) < 0) {
    return { disabled: true, reason: `Before earliest allowed date (${formatDisplayDate(policy.min)})` };
  }
  if (policy?.max && compareIso(iso, policy.max) > 0) {
    return { disabled: true, reason: `After latest allowed date (${formatDisplayDate(policy.max)})` };
  }
  const holiday = policy?.holidays?.find((h) => h.date === iso);
  const isLeave = Boolean(policy?.approvedLeaveDates?.includes(iso));
  const isBlackout = Boolean(policy?.blackoutDates?.includes(iso));
  const isConflict = Boolean(policy?.conflictDates?.includes(iso));

  if (policy?.mode === 'planning') {
    if (weekdayOf(p) === 0) {
      return { disabled: true, reason: 'Sundays are unavailable for planning' };
    }
    if (holiday) {
      return { disabled: true, reason: `Public holiday: ${holiday.name}`, badge: 'holiday' };
    }
    if (isLeave) {
      return { disabled: true, reason: 'Approved leave day — unavailable for scheduling', badge: 'leave' };
    }
    if (isBlackout) {
      return { disabled: true, reason: 'Blackout date — scheduling restricted', badge: 'blackout' };
    }
  }
  if (holiday) return { disabled: false, reason: `Public holiday: ${holiday.name}`, badge: 'holiday' };
  if (isLeave) return { disabled: false, reason: 'Approved leave day', badge: 'leave' };
  if (isBlackout) return { disabled: false, reason: 'Blackout date', badge: 'blackout' };
  if (isConflict) return { disabled: false, reason: 'Existing scheduled commitment on this date', badge: 'conflict' };
  return { disabled: false, reason: '' };
}

export interface RangePreset {
  id: string;
  label: string;
  start: string;
  end: string;
}

export function rangePresets(today: string = kampalaTodayIso()): RangePreset[] {
  const p = parseIso(today)!;
  const dow = weekdayOf(p);
  const mondayOffset = dow === 0 ? -6 : 1 - dow;
  const thisWeekStart = addDays(today, mondayOffset);
  const thisWeekEnd = addDays(thisWeekStart, 5); // Mon..Sat
  const nextWeekStart = addDays(thisWeekStart, 7);
  const nextWeekEnd = addDays(nextWeekStart, 5);
  const monthStart = toIso({ y: p.y, m: p.m, d: 1 });
  const monthEnd = toIso({ y: p.y, m: p.m, d: daysInMonth(p.y, p.m) });
  return [
    { id: 'today', label: 'Today', start: today, end: today },
    { id: 'tomorrow', label: 'Tomorrow', start: addDays(today, 1), end: addDays(today, 1) },
    { id: 'this_week', label: 'This Week', start: thisWeekStart, end: thisWeekEnd },
    { id: 'next_week', label: 'Next Week', start: nextWeekStart, end: nextWeekEnd },
    { id: 'this_month', label: 'This Month', start: monthStart, end: monthEnd },
  ];
}
