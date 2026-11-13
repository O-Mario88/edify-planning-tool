import type { Metadata } from 'next';

import { CalendarBody } from '@/components/calendar/CalendarBody';
import { askPage } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { environment } from '@/lib/environment';
import { drawerPageHref, pageQuery } from '@/lib/feedPage';

export const metadata: Metadata = { title: 'Calendar - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * The Calendar, drawn from the gateway's GetPage answer, which Go reads for
 * every staff reader (calendarpage; docs/migration/34-calendar.md). The
 * month is always asked for: the Agenda view lists the same month's days
 * (the agenda answer drops each day's date), so `view` stays on this side.
 * Partners' calendars are not Go's yet and open in the existing web.
 */
export default async function CalendarPage({ searchParams }: { searchParams: Search }) {
  const query = pageQuery(await searchParams);
  const view = query.view === 'agenda' ? 'agenda' : 'month';
  const asked = Object.fromEntries(Object.entries(query).filter(([key]) => key !== 'view'));
  const answer = await askPage('/calendar', asked);
  const existingHref = drawerPageHref(environment().existingWebUrl, '/calendar', query);
  if (!answer) return <NotMovedYet href={existingHref} />;
  return <CalendarBody answer={answer} query={query} view={view} existingHref={existingHref} now={new Date()} />;
}
