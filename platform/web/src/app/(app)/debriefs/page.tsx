import type { Metadata } from 'next';

import { askFirst } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { FieldDebriefView } from '@/components/pages/FieldDebriefView';
import { PhonePage } from '@/components/phone/PhonePage';
import { environment } from '@/lib/environment';
import { drawerPageHref, pageQuery } from '@/lib/feedPage';
import { requestView } from '@/lib/requestView';

export const metadata: Metadata = { title: 'Field Debrief Dashboard - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

export default async function FieldDebriefPage({ searchParams }: { searchParams: Search }) {
  const query = pageQuery(await searchParams);
  const existingWebUrl = environment().existingWebUrl;
  const phone = (await requestView()) === 'phone';
  const answer = await askFirst(['/debriefs', '/debriefs/'], query, !phone);
  const existingHref = drawerPageHref(existingWebUrl, '/debriefs', query);
  if (!answer) return <NotMovedYet href={existingHref} />;
  const pagePath = answer.webPath || '/debriefs';
  const drawerHref = drawerPageHref(existingWebUrl, pagePath, query);
  if (phone) return <PhonePage answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
  return <FieldDebriefView answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
}
