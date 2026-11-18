import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { Code, ConnectError } from '@connectrpc/connect';

import { NotificationCenterService } from '@/gen/edify/screens/v1/notification_center_pb';
import type { GetNotificationCenterResponse } from '@/gen/edify/screens/v1/notification_center_pb';
import { Card } from '@/components/blocks/Card';
import { FilterBar } from '@/components/blocks/FilterBar';
import { KpiStrip } from '@/components/blocks/KpiStrip';
import { PageHeader } from '@/components/blocks/PageHeader';
import { Pager } from '@/components/blocks/Pager';
import { DeliverySettings } from '@/components/notifications/DeliverySettings';
import { NotificationList } from '@/components/notifications/NotificationList';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isNotFound } from '@/lib/gateway';
import {
  NOTIFICATIONS_PATH,
  PRIORITY_CHOICES,
  STATUS_CHOICES,
  categoryChoices,
  keptQuery,
  notificationHeader,
  notificationPager,
  notificationQuery,
  notificationRequest,
  notificationStrip,
} from '@/lib/notificationCenter';
import { hrefWith } from '@/lib/pager';

export const metadata: Metadata = { title: 'Notifications — Edify' };

type Search = Promise<Record<string, string | string[] | undefined>>;

/** The gateway does not serve the page here yet (docs/migration/43). */
function isUnavailable(error: unknown): boolean {
  return error instanceof ConnectError && error.code === Code.Unavailable;
}

function NotServedHere({ href }: { href: string }) {
  return (
    <div className="mx-auto max-w-[1500px] px-4 pt-5 sm:px-6">
      <div className="card p-6">
        <h1 className="text-[length:var(--edify-text-title-size)] font-bold">This page has not moved to the new web app yet</h1>
        <p className="mt-1 text-[var(--edify-text-muted)]">It still opens in the existing web app, with the same workflow.</p>
        <a href={href} className="mt-4 inline-flex h-10 items-center rounded-[var(--radius-control)] bg-[var(--edify-accent)] px-4 font-semibold text-white">
          Open it in the existing web app
        </a>
      </div>
    </div>
  );
}

/*
 * The notification centre, drawn from the gateway's answer, which Go reads
 * (NotificationCenterService; docs/migration/43-notifications.md).
 */
export default async function NotificationsPage({ searchParams }: { searchParams: Search }) {
  const query = notificationQuery(await searchParams);
  const existingWebUrl = environment().existingWebUrl;
  const answer = await asReader(async (token): Promise<GetNotificationCenterResponse | null> => {
    try {
      return await gatewayClient(NotificationCenterService, token).getNotificationCenter(notificationRequest(query));
    } catch (error) {
      if (isNotFound(error)) notFound();
      if (isUnavailable(error)) return null;
      throw error;
    }
  });
  if (answer === null) return <NotServedHere href={`${existingWebUrl}${NOTIFICATIONS_PATH}`} />;

  const filters = answer.filters;
  const pager = notificationPager(answer, query);
  const kept = keptQuery(query);
  const actionRequiredHref = hrefWith(NOTIFICATIONS_PATH, kept, { action_required: filters?.actionRequired ? '' : 'true', page: '' });
  const hidden: Record<string, string> = {};
  if (filters?.q) hidden.q = filters.q;
  if (filters?.actionRequired) hidden.action_required = 'true';

  return (
    <div className="mx-auto max-w-[1500px] space-y-4 px-4 pb-5 pt-5 sm:px-6">
      <PageHeader header={notificationHeader()} hrefOf={() => `${existingWebUrl}${NOTIFICATIONS_PATH}`} />
      <KpiStrip strip={notificationStrip(answer)} />
      <FilterBar
        action={NOTIFICATIONS_PATH}
        label="Notification filters"
        clearHref={NOTIFICATIONS_PATH}
        hidden={hidden}
        filters={[
          { name: 'status', label: 'Status', value: filters?.status ?? 'all', options: STATUS_CHOICES },
          { name: 'priority', label: 'Priority', value: filters?.priority ?? '', options: PRIORITY_CHOICES },
          { name: 'category', label: 'Category', value: filters?.category ?? '', options: categoryChoices(answer) },
        ]}
      />
      <div className="flex items-center justify-between gap-4">
        <a href={actionRequiredHref} role="checkbox" aria-checked={filters?.actionRequired ?? false} className="flex items-center gap-2 text-[13px] font-bold text-[var(--edify-text-muted)]">
          <span aria-hidden="true" className={`grid h-4 w-4 place-items-center rounded-[4px] border border-[var(--edify-border-strong)] ${filters?.actionRequired ? 'bg-[var(--brand-primary)] text-white' : ''}`}>
            {filters?.actionRequired ? '✓' : ''}
          </span>
          Action Required Only
        </a>
        <a href={NOTIFICATIONS_PATH} className="flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-4 text-[12px] font-bold">
          Reset Filters
        </a>
      </div>
      <Card flush label="Notifications">
        <NotificationList items={answer.notifications} existingWebUrl={existingWebUrl} />
        {pager ? <Pager pager={pager} /> : null}
      </Card>
      {answer.delivery ? <DeliverySettings delivery={answer.delivery} existingWebUrl={existingWebUrl} /> : null}
    </div>
  );
}
