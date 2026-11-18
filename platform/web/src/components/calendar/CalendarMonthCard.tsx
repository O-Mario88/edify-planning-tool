/*
 * The Calendar's month card (templates/pages/calendar/index.html): its
 * toolbar (date badge, month, range, ‹ Today ›, Month / Agenda), then the
 * Monday-first grid on a wide screen and, under lg, the phone calendar; or,
 * in the Agenda view, the month's days with their events; then the legend
 * of the events' colours. A day with work to reschedule is edged red. Every event and
 * word is the gateway's answer (lib/calendarPage reads it back).
 */
import Link from 'next/link';

import type { CalendarMonth } from '@/lib/calendarPage';
import { mondayOffset, monthLinks, viewLink } from '@/lib/calendarPage';

import { BUTTON_OUTLINE, BUTTON_PRIMARY } from '../blocks/buttons';
import { Icon } from '../shell/icons';
import { CalendarAgenda } from './CalendarAgenda';
import { CalendarEventChip } from './CalendarEventChip';
import { CalendarPhone } from './CalendarPhone';
import { CalendarSelectAll } from './CalendarPick';

/** The page's weekday headings (extended_views._CALENDAR_WEEKDAY_LABELS). */
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;

export interface CalendarMonthCardProps {
  readonly month: CalendarMonth;
  readonly query: Readonly<Record<string, string>>;
  readonly view: 'month' | 'agenda';
  /** Today's day of this month (Kampala's day), or 0 when today is in another month. */
  readonly today: number;
  /** Over the phone calendar: "Your schedule" or the person's name. */
  readonly eyebrow: string;
  readonly dayEmpty: string;
}

function Toolbar({ month, query, view }: Pick<CalendarMonthCardProps, 'month' | 'query' | 'view'>) {
  const links = monthLinks(query, month.year, month.month);
  const square = `${BUTTON_OUTLINE} w-10 justify-center px-0`;
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--edify-border)] px-4 py-4 sm:px-5">
      <div className="flex items-center gap-3">
        {month.badge ? (
          <span className="grid h-12 w-[52px] place-items-center rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] leading-none" aria-hidden="true">
            <span className="text-[11px] font-bold text-[var(--brand-primary-text)] dark:text-[var(--edify-accent-text)]">{month.badge.label}</span>
            <span className="text-[20px] font-bold">{month.badge.value}</span>
          </span>
        ) : null}
        <div>
          <h2 className="text-[16px] font-bold">{month.title}</h2>
          <p className="text-[length:var(--edify-text-label-size)] font-semibold">{month.range}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
      {month.ticks ? <CalendarSelectAll /> : null}
      <nav className="flex flex-wrap items-center gap-2" aria-label="Calendar months">
        <Link href={links.previous} className={square} aria-label="Previous month"><Icon name="back" className="h-4 w-4 shrink-0" /></Link>
        <Link href={links.today} className={BUTTON_OUTLINE}>Today</Link>
        <Link href={links.next} className={square} aria-label="Next month"><Icon name="forward" className="h-4 w-4 shrink-0" /></Link>
        <Link href={viewLink(query, 'month')} className={view === 'month' ? BUTTON_PRIMARY : BUTTON_OUTLINE} aria-current={view === 'month' ? 'page' : undefined}>
          <Icon name="calendar" className="h-4 w-4" />Month
        </Link>
        <Link href={viewLink(query, 'agenda')} className={view === 'agenda' ? BUTTON_PRIMARY : BUTTON_OUTLINE} aria-current={view === 'agenda' ? 'page' : undefined}>
          <Icon name="menu" className="h-4 w-4" />Agenda
        </Link>
      </nav>
      </div>
    </header>
  );
}

function Grid({ month, today }: { month: CalendarMonth; today: number }) {
  const lead = mondayOffset(month.year, month.month);
  const trail = (7 - ((lead + month.days.length) % 7)) % 7;
  const blank = (key: string) => <div key={key} className="min-h-[158px] border-b border-r border-[var(--edify-border)] bg-[var(--edify-surface-muted)]" aria-hidden="true" />;
  return (
    <div role="grid" aria-label={month.title} className="max-lg:hidden">
      <div role="row" className="grid grid-cols-7 border-b border-[var(--edify-border)] bg-[var(--edify-surface-muted)]">
        {WEEKDAYS.map((weekday) => (
          <div key={weekday} role="columnheader" className="px-3 py-2.5 text-[12px] font-semibold uppercase text-[var(--edify-text-muted)]">{weekday}</div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {Array.from({ length: lead }, (_, index) => blank(`lead-${index}`))}
        {month.days.map((day) => (
          <article
            key={day.day}
            role="gridcell"
            data-day={day.day}
            data-day-off={day.dayOff || undefined}
            className={`min-h-[158px] min-w-0 border-b border-r border-[var(--edify-border)] p-2 ${day.day === today ? 'bg-[var(--brand-primary-soft)] outline outline-1 -outline-offset-1 outline-[var(--edify-accent)]' : 'bg-[var(--edify-card-surface)]'} ${day.dayOff ? 'shadow-[inset_0_0_0_2px_var(--edify-danger)]' : ''}`}
          >
            <div className="mb-1.5 flex items-center justify-between px-1">
              <span className={day.day === today ? 'grid h-6 w-6 place-items-center rounded-full bg-[var(--edify-accent)] text-[13px] font-bold text-white' : 'text-[13px] font-bold'}>{day.day}</span>
              {day.day === today ? <span className="text-[12px] font-medium">Today</span> : null}
            </div>
            <div className="space-y-1.5">
              {day.events.map((event, index) => <CalendarEventChip key={index} event={event} compact />)}
            </div>
          </article>
        ))}
        {Array.from({ length: trail }, (_, index) => blank(`trail-${index}`))}
      </div>
    </div>
  );
}

/** The page's legend (calendar/index.html, calendar-month__legend): each family's and kind's dot. */
const LEGEND = [
  { label: 'Visits', key: 'visit', dot: 'bg-[var(--brand-primary)]' },
  { label: 'Trainings', key: 'training', dot: 'bg-[var(--edify-success)]' },
  { label: 'Cluster work', key: 'cluster', dot: 'bg-[var(--edify-purple)]' },
  { label: 'Core schools', key: 'core', dot: 'bg-[var(--edify-chart-orange)]' },
  { label: 'Projects', key: 'project', dot: 'bg-[var(--edify-teal)]' },
  { label: 'Programme events', key: 'programme', dot: 'bg-[var(--edify-chart-pink)]' },
  { label: 'Leave', key: 'leave', dot: 'bg-[var(--edify-warning)]' },
  { label: 'Holidays', key: 'holiday', dot: 'bg-[var(--edify-danger)]' },
  { label: 'Other events', key: 'event', dot: 'bg-[var(--edify-purple)]' },
  { label: 'On a holiday or leave day: reschedule', key: 'dayoff', dot: 'border-2 border-[var(--edify-danger)] bg-[var(--edify-danger-light)]' },
] as const;

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 border-t border-[var(--edify-border)] px-4 py-3 text-[12.5px] font-medium sm:px-5" aria-label="Legend" data-block="calendar-legend">
      {LEGEND.map((entry) => (
        <li key={entry.key} className="flex items-center gap-1.5">
          <i className={`h-2.5 w-2.5 rounded-full ${entry.dot}`} aria-hidden="true" />
          {entry.label}
        </li>
      ))}
    </ul>
  );
}

export function CalendarMonthCard({ month, query, view, today, eyebrow, dayEmpty }: CalendarMonthCardProps) {
  const busy = month.days.filter((day) => day.events.length);
  return (
    <>
      {view === 'month' ? <CalendarPhone month={month} today={today} eyebrow={eyebrow} query={query} dayEmpty={dayEmpty} /> : null}
      <section aria-label={month.title} data-block="calendar-month" className={`overflow-hidden card ${view === 'month' ? 'max-lg:hidden' : ''}`}>
        <Toolbar month={month} query={query} view={view} />
        {view === 'month' ? <Grid month={month} today={today} /> : <CalendarAgenda month={month} today={today} days={busy} empty={month.empty} />}
        <Legend />
        {month.note ? <p className="border-t border-[var(--edify-border)] bg-[var(--edify-surface-muted)] px-4 py-3 text-[length:var(--edify-text-label-size)] font-medium sm:px-5">{month.note}</p> : null}
      </section>
    </>
  );
}
