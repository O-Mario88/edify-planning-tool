import type { Metadata } from 'next';

import { FeedPage } from '@/components/page/FeedPage';
import { pageQuery } from '@/lib/feedPage';

export const metadata: Metadata = { title: 'Clusters - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * Clusters, drawn from the gateway's GetPage answer, which Go reads
 * (clusterpage; docs/migration/14-districts-and-clusters.md), with each
 * card's schools loaded when it opens (14.4).
 */
export default async function ClustersPage({ searchParams }: { searchParams: Search }) {
  return <FeedPage path="/clusters" query={pageQuery(await searchParams)} />;
}
