/*
 * A page drawn from PageScreenService.GetPage, which Go answers for the
 * pages it has taken over: the header, then the blocks in the page's order,
 * then the bar for ticked rows. A reader the page refuses gets the not-found
 * page; a page (or a reader's version of it) Go does not answer yet, which a
 * gateway with no existing application behind it answers "unavailable",
 * says so and opens the existing web.
 */
import { notFound } from 'next/navigation';

import type { PageAction } from '@/gen/edify/screens/v1/page_pb';
import { PageScreenService } from '@/gen/edify/screens/v1/page_screen_pb';
import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { actionHref, drawerPageHref } from '@/lib/feedPage';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import { firstAnswer, type SpellingAnswer } from '@/lib/pageSpellings';

import { PageHeader } from '../blocks/PageHeader';
import { FeedBlocks } from './FeedBlocks';
import { NotMovedYet } from './NotMovedYet';
import { SelectionBar } from './SelectionBar';

/** The gateway's answer for one spelling of a page. */
async function askSpelling(path: string, query: Record<string, string>): Promise<SpellingAnswer<GetPageResponse>> {
  return asReader(async (token) => {
    try {
      return { kind: 'page', page: await gatewayClient(PageScreenService, token).getPage({ path, query }) };
    } catch (error) {
      if (isNotFound(error)) return { kind: 'notFound' };
      if (isUnavailable(error)) return { kind: 'unavailable' };
      throw error;
    }
  });
}

export async function askPage(path: string, query: Record<string, string>): Promise<GetPageResponse | null> {
  const answer = await askSpelling(path, query);
  if (answer.kind === 'notFound') notFound();
  return answer.kind === 'page' ? answer.page : null;
}

/**
 * The first answer among the page's spellings: some pages are answered only
 * as "/x/" (the finance pages, every oversight page), others only as "/x".
 * A spelling the gateway does not know moves on to the next
 * (lib/pageSpellings); the page is not found only when none answers.
 */
async function askFirst(paths: readonly string[], query: Record<string, string>): Promise<GetPageResponse | null> {
  const answer = await firstAnswer(paths, (path) => askSpelling(path, query));
  if (answer.kind === 'notFound') notFound();
  return answer.kind === 'page' ? answer.page : null;
}

export async function FeedPage({ path, query, alsoAs = [] }: { path: string; query: Record<string, string>; alsoAs?: readonly string[] }) {
  const existingWebUrl = environment().existingWebUrl;
  const answer = await askFirst([path, ...alsoAs], query);
  const existingHref = drawerPageHref(existingWebUrl, path, query);
  if (!answer) return <NotMovedYet href={existingHref} />;
  const pagePath = answer.webPath || path;
  const drawerHref = drawerPageHref(existingWebUrl, pagePath, query);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  return (
    <div className="mx-auto max-w-[1500px] space-y-4 px-4 pb-24 pt-5 sm:px-6 lg:pb-8" data-page={pagePath}>
      {answer.header ? <PageHeader header={answer.header} hrefOf={hrefOf} /> : null}
      <FeedBlocks blocks={answer.blocks} pagePath={pagePath} drawerHref={drawerHref} selectable={Boolean(answer.selection?.actions.length)} />
      {answer.selection?.actions.length ? <SelectionBar selection={answer.selection} pageHref={drawerHref} /> : null}
    </div>
  );
}
