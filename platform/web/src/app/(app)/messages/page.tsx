import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { MessagingService } from '@/gen/edify/messaging/v1/messaging_pb';
import type { ListThreadsResponse, ThreadRow } from '@/gen/edify/messaging/v1/messaging_pb';
import { Badge } from '@/components/blocks/Badge';
import { Card } from '@/components/blocks/Card';
import { PageHeader } from '@/components/blocks/PageHeader';
import { Pager } from '@/components/blocks/Pager';
import { TabRail } from '@/components/blocks/TabRail';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import {
  MESSAGES_PATH,
  contextTone,
  conversationHref,
  inboxPager,
  inboxTabs,
  messagesHeader,
  messagesQuery,
  messagesRequest,
  sortHidden,
} from '@/lib/messagesInbox';

export const metadata: Metadata = { title: 'Messages — Edify' };

type Search = Promise<Record<string, string | string[] | undefined>>;

function ThreadItem({ row }: { row: ThreadRow }) {
  return (
    <li>
      <a
        href={row.href}
        aria-current={row.selected ? 'true' : undefined}
        className={`flex gap-3 px-4 py-3 hover:bg-[var(--edify-surface-muted)] ${row.selected ? 'bg-[var(--brand-primary-soft)]' : ''}`}
        data-thread={row.id}
      >
        <span
          aria-hidden
          className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--edify-surface-muted)] text-[12px] font-bold text-[var(--edify-text-muted)]"
        >
          {row.isSystem ? '⚙' : row.initials}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className={`truncate ${row.unread ? 'font-bold' : 'font-semibold'} text-[var(--edify-text)]`}>{row.senderName}</span>
            <time dateTime={row.lastAt} className="shrink-0 text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">
              {row.lastAtLabel}
            </time>
          </span>
          <span className={`block truncate text-[var(--edify-text)] ${row.unread ? 'font-semibold' : ''}`}>{row.subject}</span>
          <span className="block truncate text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">{row.snippet}</span>
          {row.contextBadge || row.priorityBadge || row.starred || row.unread ? (
            <span className="mt-1 flex flex-wrap items-center gap-1.5">
              {row.unread ? <span className="sr-only">Unread</span> : null}
              {row.contextBadge ? <Badge tone={contextTone(row.contextTone)}>{row.contextBadge}</Badge> : null}
              {row.priorityBadge ? <Badge tone={contextTone(row.priorityTone)}>{row.priorityBadge}</Badge> : null}
              {row.starred ? <span aria-label="Starred">★</span> : null}
            </span>
          ) : null}
        </span>
      </a>
    </li>
  );
}

function SortForm({ answer }: { answer: ListThreadsResponse }) {
  return (
    <form method="get" action={MESSAGES_PATH} className="flex items-center gap-2">
      {Object.entries(sortHidden(answer)).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <label htmlFor="messages-sort" className="sr-only">
        Sort conversations
      </label>
      <select
        id="messages-sort"
        name="sort"
        defaultValue={answer.sorts.find((s) => s.selected)?.value ?? answer.sort}
        className="h-8 rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-2 text-[12px] font-bold"
      >
        {answer.sorts.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
      <button type="submit" className="h-8 rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 text-[12px] font-bold">
        Sort
      </button>
    </form>
  );
}

function OpenConversation({ row, existingWebUrl }: { row: ThreadRow | undefined; existingWebUrl: string }) {
  if (!row) {
    return (
      <Card label="Conversation">
        <p className="text-[var(--edify-text-muted)]">Choose a conversation to read it.</p>
      </Card>
    );
  }
  return (
    <Card label="Conversation">
      <div className="space-y-2">
        <h2 className="text-[length:var(--edify-text-heading-size)] font-semibold">{row.subject}</h2>
        <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
          {[row.senderName, row.lastAtLabel].filter(Boolean).join(' · ')}
        </p>
        <p className="text-[var(--edify-text)]">{row.snippet}</p>
        <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
          Reading and replying have not moved to the new web app yet; the conversation opens in the existing web app.
        </p>
        <a
          href={conversationHref(existingWebUrl, row.id)}
          className="inline-flex h-10 items-center rounded-[var(--radius-control)] bg-[var(--edify-accent)] px-4 font-semibold text-white"
        >
          Open the conversation
        </a>
      </div>
    </Card>
  );
}

/*
 * The Messages inbox, drawn from the gateway's answer, which Go reads
 * (MessagingService.ListThreads; docs/migration/42-messages.md): the tabs,
 * sort, conversation list, pager and Message Rules. The open conversation is
 * read in the existing web app, which marks it read.
 */
export default async function MessagesPage({ searchParams }: { searchParams: Search }) {
  const query = messagesQuery(await searchParams);
  const existingWebUrl = environment().existingWebUrl;
  const answer = await asReader(async (token): Promise<ListThreadsResponse | null> => {
    try {
      return await gatewayClient(MessagingService, token).listThreads(messagesRequest(query));
    } catch (error) {
      if (isNotFound(error)) notFound();
      if (isUnavailable(error)) return null;
      throw error;
    }
  });
  if (answer === null) return <NotMovedYet href={`${existingWebUrl}${MESSAGES_PATH}`} />;

  const { rail, counts } = inboxTabs(answer);
  const pager = inboxPager(answer);
  const open = answer.threads.find((row) => row.id === answer.selectedThreadId);
  return (
    <div className="mx-auto max-w-[1500px] space-y-3 px-4 pb-24 pt-4 sm:px-6 lg:pb-8" data-page={MESSAGES_PATH}>
      <PageHeader header={messagesHeader(answer, existingWebUrl)} hrefOf={(action) => action.href} />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <TabRail rail={rail} counts={counts} />
        <SortForm answer={answer} />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <Card flush label="Conversations">
            {answer.threads.length ? (
              <ul className="divide-y divide-[var(--edify-border)]">
                {answer.threads.map((row) => (
                  <ThreadItem key={row.id} row={row} />
                ))}
              </ul>
            ) : (
              <div className="px-4 py-6">
                <p className="font-semibold text-[var(--edify-text)]">{answer.emptyTitle}</p>
                <p className="text-[var(--edify-text-muted)]">{answer.emptyMessage}</p>
              </div>
            )}
            {pager ? <Pager pager={pager} /> : null}
          </Card>
        </div>
        <div className="space-y-4 lg:col-span-7">
          <OpenConversation row={open} existingWebUrl={existingWebUrl} />
          {answer.messageRules.length ? (
            <Card label="Message Rules">
              <h3 className="mb-2 text-[13px] font-semibold">Message Rules</h3>
              <ul className="space-y-1.5">
                {answer.messageRules.map((rule) => (
                  <li key={rule} className="flex items-start gap-2 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text-muted)]">
                    <span aria-hidden className="text-[var(--brand-primary-text)]">
                      ✓
                    </span>
                    {rule}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
