import type { Metadata } from 'next';

import { FeedPage } from '@/components/page/FeedPage';
import { pageQuery } from '@/lib/feedPage';

export const metadata: Metadata = { title: 'Planning - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * Planning, drawn from the gateway's GetPage answer, which Go reads for
 * every tab (planningpage; docs/migration/24-planning-page.md).
 */
export default async function PlanningPage({ searchParams }: { searchParams: Search }) {
  return <FeedPage path="/planning" query={pageQuery(await searchParams)} />;
}
