/**
 * The top bar's date chip: Kampala's day (the existing web reads
 * timezone.localdate(), Africa/Kampala) and its ISO week.
 */
const ZONE = 'Africa/Kampala';

export interface DateChip {
  readonly weekday: string;
  readonly date: string;
  readonly week: number;
}

function isoWeek(year: number, month: number, day: number): number {
  const date = new Date(Date.UTC(year, month - 1, day));
  const weekday = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - weekday);
  const yearStart = Date.UTC(date.getUTCFullYear(), 0, 1);
  return Math.ceil(((date.getTime() - yearStart) / 86_400_000 + 1) / 7);
}

export function dateChip(now: Date): DateChip {
  const part = (options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', { timeZone: ZONE, ...options }).format(now);
  const year = Number(part({ year: 'numeric' }));
  const month = Number(part({ month: 'numeric' }));
  const day = Number(part({ day: 'numeric' }));
  return {
    weekday: part({ weekday: 'short' }).toUpperCase(),
    date: part({ month: 'short', day: 'numeric', year: 'numeric' }),
    week: isoWeek(year, month, day),
  };
}

export function initialsOf(name: string, email: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return `${words[0]?.[0] ?? ''}${words[words.length - 1]?.[0] ?? ''}`.toUpperCase();
  if (words.length === 1) return (words[0] ?? '').slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase();
}
