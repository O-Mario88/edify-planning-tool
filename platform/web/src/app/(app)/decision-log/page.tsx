import type { Metadata } from 'next';

import { askFirst } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { DecisionLogView } from '@/components/pages/DecisionLogView';
import { PhonePage } from '@/components/phone/PhonePage';
import { environment } from '@/lib/environment';
import { drawerPageHref, pageQuery } from '@/lib/feedPage';
import { requestView } from '@/lib/requestView';

export const metadata: Metadata = { title: 'Decision Log - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

export default async function DecisionLogPage({ searchParams }: { searchParams: Search }) {
  const query = pageQuery(await searchParams);
  const existingWebUrl = environment().existingWebUrl;
  const phone = (await requestView()) === 'phone';
  const answer = await askFirst(['/decision-log', '/decision-log/'], query, !phone);
  const existingHref = drawerPageHref(existingWebUrl, '/decision-log', query);
  if (!answer) return <NotMovedYet href={existingHref} />;
  const pagePath = answer.webPath || '/decision-log';
  const drawerHref = drawerPageHref(existingWebUrl, pagePath, query);
  if (phone) return <PhonePage answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
  return <DecisionLogView answer={answer} pagePath={pagePath} />;
}
