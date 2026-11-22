import { RefreshInbox } from '@/components/blocks/RefreshInbox';
import type { Metadata } from 'next';
import { revalidatePath } from 'next/cache';
import { notFound, redirect } from 'next/navigation';

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
import { gatewayJson } from '@/lib/gatewayJson';
import {
  MESSAGES_PATH,
  contextTone,
  inboxPager,
  inboxTabs,
  messagesHeader,
  messagesQuery,
  messagesRequest,
  sortHidden,
} from '@/lib/messagesInbox';

export const metadata: Metadata = { title: 'Messages — Edify' };

type Search = Promise<Record<string, string | string[] | undefined>>;

interface ThreadMessage {
  id: string;
  senderId: string;
  senderName: string;
  body: string;
  isSystemGenerated: boolean;
  createdAt: string;
}

interface ThreadDetail {
  id: string;
  subject: string;
  priority: string;
  isSystemGenerated: boolean;
  starred: boolean;
  archived: boolean;
  participants: string[];
  messages: ThreadMessage[];
}

interface RecipientOption {
  id: string;
  name: string;
  activeRole: string;
}

async function sendReplyAction(formData: FormData) {
  'use server';
  const threadId = String(formData.get('thread_id') ?? '').trim();
  const body = String(formData.get('body') ?? '').trim();
  if (!threadId || !body) return;
  await asReader((token) =>
    gatewayJson(`/api/v1/messages/threads/${encodeURIComponent(threadId)}/reply`, token, {
      method: 'POST',
      body: { body },
    }),
  );
  revalidatePath(MESSAGES_PATH);
  redirect(`${MESSAGES_PATH}?thread=${encodeURIComponent(threadId)}`);
}

async function updateThreadStateAction(formData: FormData) {
  'use server';
  const threadId = String(formData.get('thread_id') ?? '').trim();
  const action = String(formData.get('state_action') ?? '').trim();
  if (!threadId || !action) return;
  await asReader((token) =>
    gatewayJson(`/api/v1/messages/threads/${encodeURIComponent(threadId)}/state`, token, {
      method: 'POST',
      body: { action },
    }),
  );
  revalidatePath(MESSAGES_PATH);
  redirect(`${MESSAGES_PATH}?thread=${encodeURIComponent(threadId)}`);
}

async function composeThreadAction(formData: FormData) {
  'use server';
  const recipientId = String(formData.get('recipient_id') ?? '').trim();
  const subject = String(formData.get('subject') ?? '').trim();
  const body = String(formData.get('body') ?? '').trim();
  const priority = String(formData.get('priority') ?? 'normal').trim();
  if (!recipientId || !subject || !body) {
    redirect(`${MESSAGES_PATH}?compose=1&error=${encodeURIComponent('Recipient, subject, and message body are required.')}`);
  }
  const res = await asReader((token) =>
    gatewayJson<{ threadId: string }>('/api/v1/messages/threads', token, {
      method: 'POST',
      body: { recipientIds: [recipientId], subject, body, priority },
    }),
  );
  revalidatePath(MESSAGES_PATH);
  redirect(`${MESSAGES_PATH}?thread=${encodeURIComponent(res.threadId)}`);
}

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

function ComposePanel({ recipients, errorMessage }: { recipients: readonly RecipientOption[]; errorMessage: string }) {
  return (
    <Card label="New Message">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[length:var(--edify-text-heading-size)] font-semibold">New Message</h2>
          <a href={MESSAGES_PATH} className="text-[12px] font-bold text-[var(--edify-text-muted)] hover:underline">
            Cancel
          </a>
        </div>
        {errorMessage ? (
          <p role="alert" className="rounded-[var(--radius-control)] border border-[#fecdd3] bg-[#fff1f2] px-3 py-2 text-[12px] font-semibold text-[#be123c]">
            {errorMessage}
          </p>
        ) : null}
        <form action={composeThreadAction} className="space-y-3">
          <div className="space-y-1">
            <label htmlFor="compose-recipient" className="block text-[12px] font-bold text-[var(--edify-text)]">
              Recipient
            </label>
            <select
              id="compose-recipient"
              name="recipient_id"
              required
              className="h-10 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px]"
            >
              <option value="">Select a colleague…</option>
              {recipients.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} ({r.activeRole})
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1 sm:col-span-2">
              <label htmlFor="compose-subject" className="block text-[12px] font-bold text-[var(--edify-text)]">
                Subject
              </label>
              <input
                id="compose-subject"
                name="subject"
                type="text"
                required
                maxLength={255}
                className="h-10 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px]"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="compose-priority" className="block text-[12px] font-bold text-[var(--edify-text)]">
                Priority
              </label>
              <select
                id="compose-priority"
                name="priority"
                defaultValue="normal"
                className="h-10 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px]"
              >
                <option value="normal">Normal</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <label htmlFor="compose-body" className="block text-[12px] font-bold text-[var(--edify-text)]">
              Message
            </label>
            <textarea
              id="compose-body"
              name="body"
              required
              rows={4}
              className="w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] p-3 text-[13px]"
            />
          </div>
          <button
            type="submit"
            className="inline-flex h-10 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-4 text-[13px] font-bold text-white"
          >
            Send Message
          </button>
        </form>
      </div>
    </Card>
  );
}

function OpenConversation({ detail }: { detail: ThreadDetail | null }) {
  if (!detail) {
    return (
      <Card label="Conversation">
        <p className="text-[var(--edify-text-muted)]">Choose a conversation to read it, or start a new message.</p>
      </Card>
    );
  }
  return (
    <Card label="Conversation">
      <div className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-2 border-b border-[var(--edify-border)] pb-3">
          <div>
            <h2 className="text-[length:var(--edify-text-heading-size)] font-semibold text-[var(--edify-text)]">{detail.subject}</h2>
            <p className="text-[12px] text-[var(--edify-text-muted)]">
              Participants: {detail.participants.join(', ')}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <form action={updateThreadStateAction}>
              <input type="hidden" name="thread_id" value={detail.id} />
              <input type="hidden" name="state_action" value={detail.starred ? 'unstar' : 'star'} />
              <button
                type="submit"
                className="inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 text-[12px] font-bold"
              >
                {detail.starred ? '★ Starred' : '☆ Star'}
              </button>
            </form>
            <form action={updateThreadStateAction}>
              <input type="hidden" name="thread_id" value={detail.id} />
              <input type="hidden" name="state_action" value={detail.archived ? 'unarchive' : 'archive'} />
              <button
                type="submit"
                className="inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 text-[12px] font-bold"
              >
                {detail.archived ? 'Unarchive' : 'Archive'}
              </button>
            </form>
          </div>
        </div>

        <ul className="space-y-3" aria-label="Messages in conversation">
          {detail.messages.map((m) => (
            <li key={m.id} className="rounded-[var(--radius-surface)] border border-[var(--edify-border)] bg-[var(--edify-surface-muted)]/40 p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] font-bold text-[var(--edify-text)]">{m.senderName}</span>
                <time dateTime={m.createdAt} className="text-[11px] text-[var(--edify-text-muted)]">
                  {new Date(m.createdAt).toLocaleString()}
                </time>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-[13px] text-[var(--edify-text)]">{m.body}</p>
            </li>
          ))}
        </ul>

        {detail.isSystemGenerated ? (
          <p className="rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface-muted)] px-3 py-2 text-[12px] font-semibold text-[var(--edify-text-muted)]">
            This is a read-only system notification thread. Replies are disabled.
          </p>
        ) : (
          <form action={sendReplyAction} className="space-y-2 border-t border-[var(--edify-border)] pt-3">
            <input type="hidden" name="thread_id" value={detail.id} />
            <label htmlFor="reply-body" className="block text-[12px] font-bold text-[var(--edify-text)]">
              Reply
            </label>
            <textarea
              id="reply-body"
              name="body"
              required
              rows={3}
              placeholder="Write your reply…"
              className="w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] p-3 text-[13px]"
            />
            <button
              type="submit"
              className="inline-flex h-9 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-4 text-[13px] font-bold text-white"
            >
              Send Reply
            </button>
          </form>
        )}
      </div>
    </Card>
  );
}

/*
 * Native Go-backed Messages inbox & conversation reader (Step 3C):
 * lists threads via MessagingService.ListThreads and opens, replies, composes,
 * stars, and archives natively via Go /api/v1/messages/* with zero Django handoffs.
 */
export default async function MessagesPage({ searchParams }: { searchParams: Search }) {
  const rawParams = await searchParams;
  const query = messagesQuery(rawParams);
  const composeOpen = rawParams.compose === '1';
  const composeError = typeof rawParams.error === 'string' ? rawParams.error : '';
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

  const threadId = query.thread || answer.selectedThreadId;
  let openDetail: ThreadDetail | null = null;
  let recipients: RecipientOption[] = [];

  if (composeOpen) {
    const recRes = await asReader((token) =>
      gatewayJson<{ recipients: RecipientOption[] }>('/api/v1/messages/recipients', token),
    );
    recipients = recRes.recipients;
  } else if (threadId) {
    openDetail = await asReader(async (token) => {
      try {
        return await gatewayJson<ThreadDetail>(`/api/v1/messages/threads/${encodeURIComponent(threadId)}`, token);
      } catch {
        return null;
      }
    });
  }

  const { rail, counts } = inboxTabs(answer);
  const pager = inboxPager(answer);
  return (
    <div className="mx-auto max-w-[1500px] space-y-3 px-4 pb-24 pt-4 sm:px-6 lg:pb-8" data-page={MESSAGES_PATH}>
      <RefreshInbox />
      <PageHeader header={messagesHeader(answer)} hrefOf={(action) => action.href} />
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
          {composeOpen ? <ComposePanel recipients={recipients} errorMessage={composeError} /> : <OpenConversation detail={openDetail} />}
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
