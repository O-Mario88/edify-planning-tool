import type { Metadata } from 'next';
import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';

import { Badge } from '@/components/blocks/Badge';
import { Card } from '@/components/blocks/Card';
import { asReader } from '@/lib/auth';
import { gatewayJson } from '@/lib/gatewayJson';

export const metadata: Metadata = { title: 'Support — Edify' };

interface SupportTicket {
  id: string;
  reference: string;
  title: string;
  category: string;
  description: string;
  urgency: string;
  status: string;
  reporterRole: string;
  route: string;
  resolution: string;
  createdAt: string;
}

type Search = Promise<{ route?: string | string[]; created?: string | string[]; error?: string | string[] }>;

function one(v: string | string[] | undefined): string {
  return Array.isArray(v) ? (v[v.length - 1] ?? '') : (v ?? '');
}

function urgencyTone(u: string): 'danger' | 'warning' | 'info' | 'neutral' {
  switch (u) {
    case 'critical':
      return 'danger';
    case 'high':
      return 'warning';
    case 'medium':
      return 'info';
    default:
      return 'neutral';
  }
}

async function submitTicket(formData: FormData) {
  'use server';
  const title = String(formData.get('title') ?? '').trim();
  const category = String(formData.get('category') ?? 'other').trim();
  const urgency = String(formData.get('urgency') ?? 'medium').trim();
  const description = String(formData.get('description') ?? '').trim();
  const route = String(formData.get('route') ?? '').trim();

  let ref = '';
  try {
    const res = await asReader((token) =>
      gatewayJson<{ ticket: SupportTicket }>('/api/v1/support/tickets', token, {
        method: 'POST',
        body: {
          title,
          category,
          urgency,
          description,
          context: route.startsWith('/') ? { route } : {},
        },
      }),
    );
    ref = res.ticket.reference;
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Could not submit support ticket.';
    redirect(`/support?error=${encodeURIComponent(msg)}`);
  }
  revalidatePath('/support');
  redirect(`/support?created=${encodeURIComponent(ref)}`);
}

/*
 * Native Go-backed Support Ticket page (Step 3A): submits tickets directly to
 * Go /api/v1/support/tickets and displays the signed-in reporter's own history
 * (or all tickets for Admin) with zero Django redirect.
 */
export default async function SupportPage({ searchParams }: { searchParams: Search }) {
  const sp = await searchParams;
  const routeContext = one(sp.route);
  const createdRef = one(sp.created);
  const errorMessage = one(sp.error);

  const data = await asReader((token) =>
    gatewayJson<{ tickets: SupportTicket[]; isAdmin: boolean }>('/api/v1/support/tickets', token),
  );

  return (
    <div className="mx-auto max-w-[1100px] space-y-5 px-4 pb-24 pt-5 sm:px-6 lg:pb-8" data-page="/support">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--brand-primary-text)]">Platform Support</p>
        <h1 className="text-[length:var(--edify-text-title-size)] font-bold text-[var(--edify-text)]">Report a Problem or Request Help</h1>
        <p className="mt-1 text-[13px] text-[var(--edify-text-muted)]">
          Tickets go directly to the Edify Platform Operations team and appear below with their reference number.
        </p>
      </div>

      {createdRef ? (
        <div role="status" className="rounded-[var(--radius-surface)] border border-[#a7f3d0] bg-[#ecfdf5] px-4 py-3 text-[13px] font-semibold text-[#047857]">
          Support ticket <strong>{createdRef}</strong> submitted. Platform administrators have been notified.
        </div>
      ) : null}

      {errorMessage ? (
        <div role="alert" className="rounded-[var(--radius-surface)] border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[13px] font-semibold text-[#be123c]">
          {errorMessage}
        </div>
      ) : null}

      <Card label="New Support Ticket">
        <form action={submitTicket} className="space-y-4">
          <input type="hidden" name="route" value={routeContext.startsWith('/') ? routeContext : ''} />
          <div className="space-y-1">
            <label htmlFor="support-title" className="block text-[13px] font-bold text-[var(--edify-text)]">
              Short summary
            </label>
            <input
              id="support-title"
              name="title"
              type="text"
              required
              maxLength={255}
              placeholder="e.g. Cannot reschedule a visit on My Plan"
              className="h-10 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px]"
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <label htmlFor="support-category" className="block text-[13px] font-bold text-[var(--edify-text)]">
                Category
              </label>
              <select
                id="support-category"
                name="category"
                defaultValue="bug"
                className="h-10 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px]"
              >
                <option value="bug">Bug / Unexpected Error</option>
                <option value="access">Access / Permissions</option>
                <option value="data">School / Data Issue</option>
                <option value="finance">Budget / Fund Requests</option>
                <option value="other">Other Question</option>
              </select>
            </div>
            <div className="space-y-1">
              <label htmlFor="support-urgency" className="block text-[13px] font-bold text-[var(--edify-text)]">
                Urgency
              </label>
              <select
                id="support-urgency"
                name="urgency"
                defaultValue="medium"
                className="h-10 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px]"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical (blocks field work)</option>
              </select>
            </div>
          </div>

          <div className="space-y-1">
            <label htmlFor="support-description" className="block text-[13px] font-bold text-[var(--edify-text)]">
              Details
            </label>
            <textarea
              id="support-description"
              name="description"
              rows={4}
              placeholder="Describe what you expected to happen and what occurred instead."
              className="w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] p-3 text-[13px]"
            />
          </div>

          {routeContext.startsWith('/') ? (
            <p className="text-[12px] text-[var(--edify-text-muted)]">
              Page context captured: <code className="font-mono">{routeContext}</code>
            </p>
          ) : null}

          <button
            type="submit"
            className="inline-flex h-10 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-5 text-[13px] font-bold text-white"
          >
            Submit Support Ticket
          </button>
        </form>
      </Card>

      <Card flush label={data.isAdmin ? 'All Support Tickets' : 'Your Support Tickets'}>
        <div className="border-b border-[var(--edify-border)] px-4 py-3">
          <h2 className="text-[14px] font-bold text-[var(--edify-text)]">
            {data.isAdmin ? 'All Support Tickets' : 'Your Submitted Tickets'} ({data.tickets.length})
          </h2>
        </div>
        {data.tickets.length === 0 ? (
          <div className="p-6 text-[13px] text-[var(--edify-text-muted)]">No support tickets submitted yet.</div>
        ) : (
          <ul className="divide-y divide-[var(--edify-border)]">
            {data.tickets.map((t) => (
              <li key={t.id} className="space-y-1 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[12px] font-bold text-[var(--brand-primary-text)]">{t.reference}</span>
                  <span className="font-semibold text-[var(--edify-text)]">{t.title}</span>
                  <Badge tone={urgencyTone(t.urgency)}>{t.urgency}</Badge>
                  <Badge tone="neutral">{t.status}</Badge>
                </div>
                {t.description ? <p className="text-[13px] text-[var(--edify-text-muted)]">{t.description}</p> : null}
                {t.resolution ? (
                  <p className="text-[12px] font-semibold text-[#047857]">Resolution: {t.resolution}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
