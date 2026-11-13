import type { Metadata } from 'next';

import { FeedPage } from '@/components/page/FeedPage';
import { pageQuery } from '@/lib/feedPage';

export const metadata: Metadata = { title: 'My Plan - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * My Plan, drawn from the gateway's GetPage answer. Go answers it for the
 * readers docs/migration/25-my-plan.md lists; for the others the gateway
 * has no answer yet and the page opens in the existing web.
 */
export default async function MyPlanPage({ searchParams }: { searchParams: Search }) {
  return <FeedPage path="/my-plan" query={pageQuery(await searchParams)} />;
}
