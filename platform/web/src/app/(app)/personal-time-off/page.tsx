import type { Metadata } from 'next';

import { askFirst } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { PersonalTimeOffView } from '@/components/pages/PersonalTimeOffView';
import { PhonePage } from '@/components/phone/PhonePage';
import { environment } from '@/lib/environment';
import { drawerPageHref, pageQuery } from '@/lib/feedPage';
import { requestView } from '@/lib/requestView';

export const metadata: Metadata = { title: 'Personal Time Off - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

export default async function PersonalTimeOffPage({ searchParams }: { searchParams: Search }) {
  const query = pageQuery(await searchParams);
  const existingWebUrl = environment().existingWebUrl;
  const phone = (await requestView()) === 'phone';
  const answer = await askFirst(['/personal-time-off/', '/personal-time-off'], query, !phone);
  const existingHref = drawerPageHref(existingWebUrl, '/personal-time-off/', query);
  if (!answer) return <NotMovedYet href={existingHref} />;
  const pagePath = '/personal-time-off';
  const drawerHref = drawerPageHref(existingWebUrl, answer.webPath || '/personal-time-off/', query);
  if (phone) return <PhonePage answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
  return <PersonalTimeOffView answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
}
