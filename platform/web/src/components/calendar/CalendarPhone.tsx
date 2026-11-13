'use client';
/*
 * The Calendar under lg (the page's calendar-mobile section): the month as a
 * small grid with a dot on each day that has events, ‹ Today › around it,
 * and the chosen day's events under it ("All month" shows every day).
 * Today is chosen when the month is today's.
 */
import Link from 'next/link';
import { useState } from 'react';

import type { CalendarMonth } from '@/lib/calendarPage';
import { mondayOffset, monthLinks } from '@/lib/calendarPage';

import { Icon } from '../shell/icons';
import { CalendarAgenda } from './CalendarAgenda';

const INITIALS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'] as const;

export interface CalendarPhoneProps {
  readonly month: CalendarMonth;
  readonly today: number;
  readonly eyebrow: string;
  readonly query: Readonly<Record<string, string>>;
  /** What a chosen day with nothing says ("No matching events for this date and event type."). */
  readonly dayEmpty: string;
}

function longDate(month: CalendarMonth, day: number): string {
  return new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(month.year, month.month - 1, day)));
}

export function CalendarPhone({ month, today, eyebrow, query, dayEmpty }: CalendarPhoneProps) {
  const [chosen, setChosen] = useState(today);
  const links = monthLinks(query, month.year, month.month);
  const lead = mondayOffset(month.year, month.month);
  const shown = month.days.filter((day) => day.events.length && (!chosen || day.day === chosen));
  return (
    <section className="overflow-hidden rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-sm)] lg:hidden" aria-label={month.title} data-block="calendar-phone">
      <header className="flex items-center justify-between px-4 pt-4">
        <div>
          <p className="text-[12px] font-semibold uppercase">{eyebrow}</p>
          <h2 className="text-[16px] font-bold">{month.title}</h2>
        </div>
        <nav className="flex items-center gap-3" aria-label="Calendar months">
          <Link href={links.previous} aria-label="Previous month"><Icon name="back" className="h-4 w-4 shrink-0" /></Link>
          <Link href={links.today} className="text-[13px] font-semibold text-[var(--brand-primary-text)] dark:text-[var(--edify-accent-text)]">Today</Link>
          <Link href={links.next} aria-label="Next month"><Icon name="forward" className="h-4 w-4 shrink-0" /></Link>
        </nav>
      </header>
      <div className="grid grid-cols-7 gap-y-1 px-3 pb-4 pt-3 text-center" role="grid" aria-label={month.title}>
        {INITIALS.map((initial, index) => (
          <span key={index} role="columnheader" className="pb-1 text-[12px] font-semibold">{initial}</span>
        ))}
        {Array.from({ length: lead }, (_, index) => <span key={`lead-${index}`} aria-hidden="true" />)}
        {month.days.map((day) => (
          <button
            key={day.day}
            type="button"
            role="gridcell"
            aria-selected={chosen === day.day}
            aria-label={`${longDate(month, day.day)}${day.events.length ? `, ${day.events.length} events` : ''}`}
            onClick={() => setChosen(day.day)}
            className="flex h-10 flex-col items-center justify-center"
          >
            <span className={`grid h-8 w-8 place-items-center rounded-full text-[14px] font-semibold ${chosen === day.day ? 'bg-[var(--edify-accent)] text-white' : ''} ${day.day === today && chosen !== day.day ? 'ring-2 ring-[var(--edify-accent)]' : ''}`}>{day.day}</span>
            <i className={`h-1 w-1 rounded-full ${day.events.length ? 'bg-[var(--edify-accent)]' : 'bg-transparent'}`} aria-hidden="true" />
          </button>
        ))}
      </div>
      <div className="border-t border-[var(--edify-border)] py-3">
        <div className="px-4">
          <p className="text-[12px] font-semibold uppercase">Selected day</p>
          <h3 className="text-[16px] font-bold">{chosen ? longDate(month, chosen) : month.title}</h3>
          <button type="button" onClick={() => setChosen(0)} aria-pressed={!chosen} className="mt-2 rounded-full bg-[var(--brand-primary-soft)] px-3 py-1.5 text-[13px] font-semibold">All month</button>
        </div>
        <CalendarAgenda month={month} today={today} days={shown} empty={chosen ? dayEmpty : month.empty} />
      </div>
    </section>
  );
}
