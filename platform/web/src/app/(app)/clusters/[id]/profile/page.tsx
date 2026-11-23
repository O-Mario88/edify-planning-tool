import type { Metadata } from 'next';

import { ClusterProfilePage } from '@/components/profile/ClusterProfilePage';
import { pageQuery } from '@/lib/feedPage';

export const metadata: Metadata = { title: 'Cluster Profile - Edify Command Center' };

type Params = Promise<{ id: string }>;
type Search = Promise<Record<string, string | string[] | undefined>>;

/* The address the existing Cluster Profile lives at: the same page. */
export default async function ClusterProfileRoute({ params, searchParams }: { params: Params; searchParams: Search }) {
  const { id } = await params;
  return <ClusterProfilePage clusterId={decodeURIComponent(id)} query={pageQuery(await searchParams)} />;
}
