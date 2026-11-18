import { FeedPage } from '@/components/page/FeedPage';
import { pageQuery } from '@/lib/feedPage';

type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * Closed Schools, which Go draws at /schools/closed. A route of its own:
 * without it /schools/[id] read "closed" as a school's id and answered
 * not found.
 */
export default async function ClosedSchoolsPage({ searchParams }: { searchParams: Search }) {
  return <FeedPage path="/schools/closed" alsoAs={['/schools/closed/']} query={pageQuery(await searchParams)} />;
}
