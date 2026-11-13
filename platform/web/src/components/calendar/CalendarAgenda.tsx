/*
 * The month's days that have events, each with its date and its events (the
 * page's agenda list): the Agenda view, and the phone calendar's day list.
 */
import type { CalendarDay, CalendarMonth } from '@/lib/calendarPage';

import { CalendarEventChip } from './CalendarEventChip';

function dayHeading(month: CalendarMonth, day: number): string {
  // The agenda's "l j F": "Friday 13 November".
  const date = new Date(Date.UTC(month.year, month.month - 1, day));
  const weekday = new Intl.DateTimeFormat('en-GB', { weekday: 'long', timeZone: 'UTC' }).format(date);
  const name = new Intl.DateTimeFormat('en-GB', { month: 'long', timeZone: 'UTC' }).format(date);
  return `${weekday} ${day} ${name}`;
}

export function CalendarAgenda({ month, today, days, empty }: { month: CalendarMonth; today: number; days: readonly CalendarDay[]; empty: string }) {
  if (!days.length) return <p className="px-4 py-5 font-medium sm:px-5">{empty}</p>;
  return (
    <ol className="divide-y divide-[var(--edify-table-divider)]">
      {days.map((day) => (
        <li key={day.day} className="px-4 py-3 sm:px-5" data-day={day.day}>
          <h3 className="mb-2 flex items-center gap-2 text-[length:var(--edify-text-label-size)] font-bold">
            <time dateTime={`${month.year}-${String(month.month).padStart(2, '0')}-${String(day.day).padStart(2, '0')}`}>{dayHeading(month, day.day)}</time>
            {day.day === today ? <span className="rounded-full bg-[var(--brand-primary-soft)] px-2 text-[12px] font-semibold text-[var(--brand-primary-text)]">Today</span> : null}
          </h3>
          <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
            {day.events.map((event, index) => <CalendarEventChip key={index} event={event} />)}
          </div>
        </li>
      ))}
    </ol>
  );
}

