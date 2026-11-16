import { FeedPage } from '@/components/page/FeedPage';
import { pageQuery } from '@/lib/feedPage';

type Params = Promise<{ rest: string[] }>;
type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * Every page without a screen of its own here is drawn from the gateway's
 * GetPage answer in the desktop layout (header, filters, figures, tables),
 * as Planning and Clusters are. A page the gateway does not answer says so
 * and opens the same page of the existing web, rather than drawing
 * something that looks finished and is not.
 */
export default async function RestPage({ params, searchParams }: { params: Params; searchParams: Search }) {
  const { rest } = await params;
  const path = `/${rest.map((part) => encodeURIComponent(decodeURIComponent(part))).join('/')}`;
  return <FeedPage path={path} alsoAs={[`${path}/`]} query={pageQuery(await searchParams)} />;
}
