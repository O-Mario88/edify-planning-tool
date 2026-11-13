import type { Metadata } from 'next';

import { FeedPage } from '@/components/page/FeedPage';
import { pageQuery } from '@/lib/feedPage';

export const metadata: Metadata = { title: 'Work Plan - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * The Work Plan, drawn from the gateway's GetPage answer, which Go reads for
 * every role the page admits (workplan; docs/migration/35-work-plan.md).
 * Its drawers, the export workbook and the approval decisions open on the
 * existing web.
 */
export default async function WorkPlanPage({ searchParams }: { searchParams: Search }) {
  return <FeedPage path="/work-plan" query={pageQuery(await searchParams)} />;
}
