import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { ListThreadsResponseSchema } from '@/gen/edify/messaging/v1/messaging_pb';

import { conversationHref, inboxPager, inboxTabs, messagesQuery, messagesRequest, sortHidden } from './messagesInbox';

const answer = (over: MessageInitShape<typeof ListThreadsResponseSchema> = {}) =>
  create(ListThreadsResponseSchema, {
    tabs: [
      { key: 'all', label: 'All', hasCount: true, count: 12, active: false },
      { key: 'unread', label: 'Unread', hasCount: true, count: 3, active: true },
      { key: 'sent', label: 'Sent', active: false },
    ],
    activeTab: 'unread',
    sort: 'oldest',
    search: 'kasese',
    ...over,
  });

describe('messagesQuery', () => {
  it('reads each key’s last value, as the view does', () => {
    expect(messagesQuery({ tab: ['all', 'unread'], page: '2', other: 'x' })).toEqual({ tab: 'unread', page: '2' });
  });

  it('asks for what the address holds and nothing for what it does not', () => {
    expect(messagesRequest({ thread: 't1' })).toEqual({ tab: '', q: '', sort: '', page: '', thread: 't1' });
  });
});

describe('inboxTabs', () => {
  it('links each tab with the search and sort kept, and the page and open thread dropped', () => {
    const { rail, counts } = inboxTabs(answer());
    expect(rail.tabs.map((t) => [t.label, t.href, t.active])).toEqual([
      ['All', '/messages?q=kasese&sort=oldest', false],
      ['Unread', '/messages?tab=unread&q=kasese&sort=oldest', true],
      ['Sent', '/messages?tab=sent&q=kasese&sort=oldest', false],
    ]);
    expect(counts).toEqual([12, 3, undefined]);
  });

  it('writes the default tab and sort as no query at all', () => {
    const { rail } = inboxTabs(answer({ activeTab: 'all', sort: 'newest', search: '' }));
    expect(rail.tabs[0]?.href).toBe('/messages');
  });
});

describe('sortHidden', () => {
  it('sends the tab and search beside the sort, never the old sort', () => {
    expect(sortHidden(answer())).toEqual({ tab: 'unread', q: 'kasese' });
  });
});

describe('inboxPager', () => {
  it('draws no pager on one page', () => {
    expect(inboxPager(answer({ pager: { shown: false } }))).toBeNull();
  });

  it('keeps the gateway’s summary and links, the current page and gaps unlinked', () => {
    const pager = inboxPager(
      answer({
        pager: {
          shown: true,
          summary: 'Showing 1–8 of 20',
          links: [
            { label: '1', page: 1, current: true, href: '/messages?page=1' },
            { label: '…', gap: true },
            { label: '3', page: 3, href: '/messages?page=3' },
          ],
        },
      }),
    );
    expect(pager?.summary).toBe('Showing 1–8 of 20');
    expect(pager?.pages.map((p) => [p.label, p.href, p.current])).toEqual([
      ['1', '', true],
      ['…', '', false],
      ['3', '/messages?page=3', false],
    ]);
  });
});

describe('conversationHref', () => {
  it('opens the conversation in the existing web app, which marks it read', () => {
    expect(conversationHref('https://existing.test', 'a b')).toBe('https://existing.test/messages?thread=a%20b');
  });
});
