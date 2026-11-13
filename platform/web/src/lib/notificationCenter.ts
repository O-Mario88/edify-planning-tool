/**
 * The notification centre's answer (NotificationCenterService, read by Go:
 * docs/migration/43-notifications.md) laid out as the page's blocks. Only
 * words that live in the Django template are written here
 * (templates/pages/notifications/index.html); every figure, label, choice,
 * notification, page and setting comes from the gateway.
 */
import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';

import type {
  GetNotificationCenterRequestSchema,
  GetNotificationCenterResponse,
} from '@/gen/edify/screens/v1/notification_center_pb';
import { PageHeaderSchema, PagePagerSchema, PageStripSchema } from '@/gen/edify/screens/v1/page_pb';
import type { PageHeader, PagePager, PageStrip } from '@/gen/edify/screens/v1/page_pb';

import { hrefWith } from './pager';

export const NOTIFICATIONS_PATH = '/notifications';

/** The query keys the existing view reads. */
const KEYS = ['status', 'priority', 'category', 'action_required', 'q', 'page', 'settings'] as const;

export type NotificationQuery = Readonly<Partial<Record<(typeof KEYS)[number], string>>>;

/** The address's query, each key's last value (Django's QueryDict.get). */
export function notificationQuery(search: Readonly<Record<string, string | string[] | undefined>>): NotificationQuery {
  const out: Partial<Record<(typeof KEYS)[number], string>> = {};
  for (const key of KEYS) {
    const value = search[key];
    const last = Array.isArray(value) ? value[value.length - 1] : value;
    if (last !== undefined) out[key] = last;
  }
  return out;
}

/** The request: what the address holds, read as the view reads it. */
export function notificationRequest(query: NotificationQuery): MessageInitShape<typeof GetNotificationCenterRequestSchema> {
  return {
    ...(query.status !== undefined ? { status: query.status } : {}),
    priority: query.priority ?? '',
    category: query.category ?? '',
    actionRequired: query.action_required === 'true',
    q: query.q ?? '',
    page: query.page ?? '',
    settingsSaved: query.settings === 'saved',
  };
}

export function notificationHeader(): PageHeader {
  return create(PageHeaderSchema, {
    eyebrow: 'Communication',
    title: 'Notifications',
    description: 'Edify Alert Operations · Keep Track of Actionable Tasks',
    actions: [
      { key: 'mark_all_read', label: 'Mark All Read', enabled: true },
      { key: 'archive_all_read', label: 'Archive All Read', enabled: true },
    ],
  });
}

/** The two figures (the template's legacy_kpi_item pair). */
export function notificationStrip(answer: GetNotificationCenterResponse): PageStrip {
  return create(PageStripSchema, {
    title: 'Notification attention',
    metrics: [
      { label: 'Action required', value: String(answer.kpis?.actionRequired ?? 0), helper: 'Unread items needing a response', tone: 'warning' },
      { label: 'Critical tasks', value: String(answer.kpis?.critical ?? 0), helper: 'Highest-priority notifications', tone: 'danger' },
    ],
  });
}

export interface Choice {
  readonly value: string;
  readonly label: string;
}

export const STATUS_CHOICES: readonly Choice[] = [
  { value: 'all', label: 'All (except archived)' },
  { value: 'unread', label: 'Unread' },
  { value: 'read', label: 'Read' },
  { value: 'archived', label: 'Archived' },
];

export const PRIORITY_CHOICES: readonly Choice[] = [
  { value: '', label: 'All Priorities' },
  { value: 'low', label: 'Low' },
  { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'High' },
  { value: 'urgent', label: 'Critical / Urgent' },
];

/**
 * The Category choices. The existing page can list a category once for each
 * moment one was raised (docs/migration/43, "Found by comparing"); a select
 * offers each choice once, so repeats are drawn once, in the answer's order.
 */
export function categoryChoices(answer: GetNotificationCenterResponse): Choice[] {
  const seen = new Set<string>();
  const out: Choice[] = [{ value: '', label: 'All Categories' }];
  for (const option of answer.filters?.categories ?? []) {
    if (seen.has(option.value)) continue;
    seen.add(option.value);
    out.push({ value: option.value, label: option.label });
  }
  return out;
}

/** The query the filters and pager keep (everything but the page). */
export function keptQuery(query: NotificationQuery): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(query)) {
    if (key !== 'page' && key !== 'settings' && value) out[key] = value;
  }
  return out;
}

/** The pager under the list; absent when everything fits on one page. */
export function notificationPager(answer: GetNotificationCenterResponse, query: NotificationQuery): PagePager | undefined {
  const info = answer.page;
  if (!info || info.totalPages <= 1) return undefined;
  const total = Number(info.total);
  const first = (info.page - 1) * info.pageSize + 1;
  const last = Math.min(info.page * info.pageSize, total);
  const kept = keptQuery(query);
  return create(PagePagerSchema, {
    summary: `Showing ${first}–${last} of ${total}`,
    pages: answer.pageNumbers.map((number) =>
      number === 0
        ? { label: '…' }
        : {
            label: String(number),
            href: number === info.page ? '' : hrefWith(NOTIFICATIONS_PATH, kept, { page: String(number) }),
            current: number === info.page,
          },
    ),
  });
}

/** The colour a notification's icon and priority pill take (the template's priority branches). */
export function priorityTone(priority: string): 'danger' | 'warning' | 'info' | 'neutral' {
  if (priority === 'urgent') return 'danger';
  if (priority === 'high') return 'warning';
  if (priority === 'normal') return 'info';
  return 'neutral';
}

/** The pill beside the title: rose for urgent, amber for high, grey otherwise. */
export function priorityPillTone(priority: string): 'danger' | 'warning' | 'neutral' {
  const tone = priorityTone(priority);
  return tone === 'info' ? 'neutral' : tone;
}
