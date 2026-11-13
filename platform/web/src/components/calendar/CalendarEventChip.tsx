/*
 * One event in a day: its title and the line under it (the school, the
 * cluster, a holiday's kind). An activity opens its own page; leave,
 * holidays, organization events and work the reader may not open are text.
 */
import Link from 'next/link';

import type { CalendarEvent } from '@/lib/calendarPage';
import { resolveHref } from '@/lib/feedPage';

export function CalendarEventChip({ event, compact = false }: { event: CalendarEvent; compact?: boolean }) {
  const href = resolveHref('/calendar', event.href);
  const lines = (
    <>
      <span className={`block font-semibold ${compact ? 'truncate' : ''}`}>{event.title}</span>
      {event.caption ? <span className={`block font-medium text-[var(--edify-text-muted)] ${compact ? 'truncate' : ''}`}>{event.caption}</span> : null}
    </>
  );
  const shape = 'block min-w-0 rounded-[6px] bg-[var(--brand-primary-soft)] px-2 py-1 text-[12.5px] leading-snug';
  if (!href) return <div className={shape} data-event>{lines}</div>;
  return (
    <Link href={href} className={`${shape} text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-accent-text)]`} title={compact ? `${event.title}${event.caption ? ` · ${event.caption}` : ''}` : undefined} data-event>
      {lines}
    </Link>
  );
}
