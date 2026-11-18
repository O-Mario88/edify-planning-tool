/**
 * The Messages inbox's answer (MessagingService.ListThreads, read by Go:
 * docs/migration/42-messages.md) laid out as the page's blocks. Every label,
 * count, row and page comes from the gateway; the only words written here are
 * the template's own (templates/pages/messages/index.html).
 *
 * Opening a conversation marks it read, a save Go does not make yet (doc 42,
 * piece 2), so the conversation itself opens in the existing web app.
 */
import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';

import type { ListThreadsRequestSchema, ListThreadsResponse } from '@/gen/edify/messaging/v1/messaging_pb';
import { PageHeaderSchema, PageLinkTabsSchema, PagePagerSchema } from '@/gen/edify/screens/v1/page_pb';
import type { PageHeader, PageLinkTabs, PagePager } from '@/gen/edify/screens/v1/page_pb';

import { hrefWith } from './pager';

export const MESSAGES_PATH = '/messages';

/** The query keys the existing view reads. */
const KEYS = ['tab', 'q', 'sort', 'page', 'thread'] as const;

export type MessagesQuery = Readonly<Partial<Record<(typeof KEYS)[number], string>>>;

/** The address's query, each key's last value (Django's QueryDict.get). */
export function messagesQuery(search: Readonly<Record<string, string | string[] | undefined>>): MessagesQuery {
  const out: Partial<Record<(typeof KEYS)[number], string>> = {};
  for (const key of KEYS) {
    const value = search[key];
    const last = Array.isArray(value) ? value[value.length - 1] : value;
    if (last !== undefined) out[key] = last;
  }
  return out;
}

export function messagesRequest(query: MessagesQuery): MessageInitShape<typeof ListThreadsRequestSchema> {
  return { tab: query.tab ?? '', q: query.q ?? '', sort: query.sort ?? '', page: query.page ?? '', thread: query.thread ?? '' };
}

/** The header as the answer words it, with the template's two controls. */
export function messagesHeader(answer: ListThreadsResponse, existingWebUrl: string): PageHeader {
  return create(PageHeaderSchema, {
    eyebrow: answer.eyebrow,
    title: answer.title,
    description: answer.description,
    actions: [
      { key: 'compose', label: 'New Message', primary: true, enabled: true, href: `${existingWebUrl}${MESSAGES_PATH}/new` },
      { key: 'settings', label: 'Message settings', enabled: true, href: '/settings' },
    ],
  });
}

/** The query a tab or the sort keeps: the search and sort travel, the page and open thread do not. */
function kept(answer: ListThreadsResponse): Record<string, string> {
  const out: Record<string, string> = {};
  if (answer.activeTab && answer.activeTab !== 'all') out.tab = answer.activeTab;
  if (answer.search) out.q = answer.search;
  if (answer.sort && answer.sort !== 'newest') out.sort = answer.sort;
  return out;
}

/** The inbox tabs as a link rail, each carrying the search and sort. */
export function inboxTabs(answer: ListThreadsResponse): { rail: PageLinkTabs; counts: (number | undefined)[] } {
  const base = kept(answer);
  const rail = create(PageLinkTabsSchema, {
    label: 'Message inbox views',
    scrolls: true,
    tabs: answer.tabs.map((tab) => ({
      label: tab.label,
      href: hrefWith(MESSAGES_PATH, base, { tab: tab.key === 'all' ? '' : tab.key }),
      active: tab.active,
    })),
  });
  return { rail, counts: answer.tabs.map((tab) => (tab.hasCount ? tab.count : undefined)) };
}

/** The fields the sort form sends beside the sort, so a change keeps the tab and search. */
export function sortHidden(answer: ListThreadsResponse): Record<string, string> {
  const out = kept(answer);
  delete out.sort;
  return out;
}

/** The pager, drawn only past one page, as the gateway writes it. */
export function inboxPager(answer: ListThreadsResponse): PagePager | null {
  const pager = answer.pager;
  if (!pager?.shown) return null;
  return create(PagePagerSchema, {
    summary: pager.summary,
    pages: pager.links.map((link) => ({ label: link.label, href: link.gap || link.current ? '' : link.href, current: link.current })),
  });
}

/** The badge colour each record kind and priority is drawn in (the existing page's context tones). */
export function contextTone(tone: string): string {
  switch (tone) {
    case 'finance':
      return 'warning';
    case 'leave':
      return 'success';
    case 'alert':
      return 'danger';
    case 'plain':
      return 'neutral';
    default:
      return 'info';
  }
}

/** Where the open conversation is read and answered: the existing web app, which marks it read. */
export function conversationHref(existingWebUrl: string, threadId: string): string {
  return `${existingWebUrl}${MESSAGES_PATH}?thread=${encodeURIComponent(threadId)}`;
}
