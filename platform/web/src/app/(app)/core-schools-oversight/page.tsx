import type { Metadata } from 'next';

import { askFirst } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { CoreSchoolOversightView } from '@/components/pages/CoreSchoolOversightView';
import { PhonePage } from '@/components/phone/PhonePage';
import { environment } from '@/lib/environment';
import { drawerPageHref, pageQuery } from '@/lib/feedPage';
import { requestView } from '@/lib/requestView';

export const metadata: Metadata = { title: 'Core School Oversight - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

export default async function CoreSchoolOversightPage({ searchParams }: { searchParams: Search }) {
  const query = pageQuery(await searchParams);
  const existingWebUrl = environment().existingWebUrl;
  const phone = (await requestView()) === 'phone';
  const answer = await askFirst(['/core-schools-oversight/', '/core-schools-oversight'], query, !phone);
  const existingHref = drawerPageHref(existingWebUrl, '/core-schools-oversight/', query);
  if (!answer) return <NotMovedYet href={existingHref} />;
  const pagePath = '/core-schools-oversight';
  const drawerHref = drawerPageHref(existingWebUrl, answer.webPath || '/core-schools-oversight/', query);
  if (phone) return <PhonePage answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
  return <CoreSchoolOversightView answer={answer} pagePath={pagePath} drawerHref={drawerHref} />;
}
