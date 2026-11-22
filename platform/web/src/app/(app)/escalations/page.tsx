import type { Metadata } from 'next';

import { askFirst } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { EscalationsView } from '@/components/pages/EscalationsView';
import { PhonePage } from '@/components/phone/PhonePage';
import { environment } from '@/lib/environment';
import { drawerPageHref, pageQuery } from '@/lib/feedPage';
import { requestView } from '@/lib/requestView';

export const metadata: Metadata = { title: 'Escalations - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

export default async function EscalationsPage({ searchParams }: { searchParams: Search }) {
  const query = pageQuery(await searchParams);
  const existingWebUrl = environment().existingWebUrl;
  const phone = (await requestView()) === 'phone';
  const answer = await askFirst(['/escalations', '/escalations/'], query, !phone);
  const existingHref = drawerPageHref(existingWebUrl, '/escalations', query);
  if (!answer) return <NotMovedYet href={existingHref} />;
  const pagePath = answer.webPath || '/escalations';
  const drawerHref = drawerPageHref(existingWebUrl, pagePath, query);
  if (phone) return <PhonePage answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
  return <EscalationsView answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
}
