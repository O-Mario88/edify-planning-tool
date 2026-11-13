/*
 * One event in a day (partials/calendar/event.html): its title and the line
 * under it, in its family's colour (calendar-workspace.css): work by its
 * programme family, leave, holidays and organization events by kind. A
 * later day of a run carries a dotted edge; work on a holiday or a leave day
 * the holiday's colour with a solid edge. An activity the reader may move or
 * cancel has a tick box beside its link for the page's bar; ticking one day
 * of a run ticks every day of it (CalendarPick). An activity opens its own
 * page; leave, holidays, organization events and work the reader may not
 * open are text.
 */
import Link from 'next/link';

import type { CalendarEvent } from '@/lib/calendarPage';
import { resolveHref } from '@/lib/feedPage';

import { CalendarPick } from './CalendarPick';

/** Each colour family's chip (calendar-workspace.css, .calendar-event--<family>). */
const FAMILY_TONES: Readonly<Record<string, string>> = {
  activity: 'bg-[var(--brand-primary-soft)] text-[var(--brand-primary-text)]',
  visit: 'bg-[var(--brand-primary-soft)] text-[var(--brand-primary-text)]',
  training: 'bg-[var(--edify-success-light)] text-[var(--edify-success-text)]',
  cluster: 'bg-[var(--edify-purple-light)] text-[var(--edify-purple-text)]',
  core: 'bg-[color-mix(in_oklab,var(--edify-chart-orange)_10%,transparent)] text-[color-mix(in_oklab,var(--edify-chart-orange)_55%,var(--edify-text))]',
  project: 'bg-[var(--edify-teal-light)] text-[color-mix(in_oklab,var(--edify-teal)_45%,var(--edify-text))]',
  programme: 'bg-[color-mix(in_oklab,var(--edify-chart-pink)_10%,transparent)] text-[color-mix(in_oklab,var(--edify-chart-pink)_50%,var(--edify-text))]',
  leave: 'bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)]',
  holiday: 'bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)]',
  event: 'bg-[color-mix(in_oklab,var(--edify-purple)_12%,var(--edify-surface))] text-[color-mix(in_oklab,var(--edify-purple)_68%,var(--edify-text))]',
};

/** Work on a public holiday or its owner's leave day: the holiday's colour, a solid edge. */
const DAY_OFF_TONE = 'bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)] border-l-[3px] border-solid border-[var(--edify-danger)]';
/** A later day of a run: the same chip, carried over from the day before. */
const CONTINUED = 'border-l-[3px] border-dotted border-current rounded-l-none';

export function toneOf(event: Pick<CalendarEvent, 'kind' | 'family' | 'dayOff'>): string {
  if (event.dayOff) return DAY_OFF_TONE;
  return FAMILY_TONES[event.family || event.kind] ?? FAMILY_TONES.activity ?? '';
}

export function CalendarEventChip({ event, compact = false }: { event: CalendarEvent; compact?: boolean }) {
  const href = resolveHref('/calendar', event.href);
  const lines = (
    <>
      <span className={`block font-semibold ${compact ? 'truncate' : ''}`}>{event.title}</span>
      {event.caption ? <span className={`block font-medium opacity-80 ${compact ? 'truncate' : ''}`}>{event.caption}</span> : null}
    </>
  );
  const shape = `block min-w-0 rounded-[6px] px-2 py-1 text-[12.5px] leading-snug ${toneOf(event)} ${event.continued && !event.dayOff ? CONTINUED : ''}`;
  const marks = { 'data-event': event.kind, 'data-family': event.family || undefined, 'data-continued': event.continued || undefined, 'data-day-off': event.dayOff || undefined };
  const title = compact ? `${event.title}${event.caption ? ` · ${event.caption}` : ''}` : undefined;
  const body = href ? (
    <Link href={href} className="block min-w-0 flex-1 hover:underline" title={title}>
      {lines}
    </Link>
  ) : (
    <span className="block min-w-0 flex-1" title={title}>{lines}</span>
  );
  return (
    <div className={`${shape} flex items-start gap-1.5`} {...marks}>
      {event.pickId ? <CalendarPick id={event.pickId} label={`Select ${event.title}${event.caption ? `, ${event.caption}` : ''}`} /> : null}
      {body}
    </div>
  );
}
