/*
 * The notification feed (pages/notifications/index.html): each notification
 * with its priority icon, title, category and priority pills, the Action
 * Required badge, its body, when it was raised, who asked and its record,
 * and on the right the record's button, Mark read and Archive. Unread rows
 * carry the soft blue. Every word that is data is the gateway's.
 *
 */
import { NotificationButton } from './NotificationButton';
import { NotificationStatusAction } from '@/gen/edify/screens/v1/notification_center_pb';
import type { NotificationItem } from '@/gen/edify/screens/v1/notification_center_pb';
import { Icon } from '@/components/shell/icons';
import { badgeClasses } from '@/components/blocks/tones';
import { priorityPillTone, priorityTone } from '@/lib/notificationCenter';

const PILL = 'inline-flex items-center rounded-full border px-2 py-0.5 text-[length:var(--edify-text-micro-size)]';
const ICON_TONE: Readonly<Record<string, string>> = {
  danger: 'border-[#fecdd3] bg-[#fff1f2] text-[#e11d48]',
  warning: 'border-[var(--edify-warning-border)] bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)]',
  info: 'border-[var(--brand-primary-border)] bg-[var(--brand-primary-soft)] text-[var(--brand-primary-text)]',
  neutral: 'border-[var(--edify-border)] bg-[var(--edify-surface-muted)] text-[var(--edify-text-muted)]',
};

function resolveTargetHref(targetRoute: string, existingWebUrl: string): string {
  if (!targetRoute) return '';
  if (targetRoute.startsWith('http://') || targetRoute.startsWith('https://')) return targetRoute;
  // When Django is absent (cutover/staging), stay inside the Next.js web app.
  // When existingWebUrl is configured (hybrid mode), open notification targets
  // on the existing application so unported pages (e.g. /strategic-priorities,
  // /hr/performance-cycle) remain reachable.
  if (!existingWebUrl) return targetRoute;
  return `${existingWebUrl}${targetRoute}`;
}

function Row({ item, existingWebUrl }: { item: NotificationItem; existingWebUrl: string }) {
  const tone = priorityTone(item.priority);
  const href = resolveTargetHref(item.targetRoute, existingWebUrl);
  return (
    <li
      data-notification={item.id}
      className={`flex flex-wrap items-start gap-3 p-4 sm:flex-nowrap sm:gap-4 sm:p-5 ${item.unread ? 'bg-[var(--brand-primary-soft)]/60' : ''}`}
    >
      <span aria-hidden="true" className={`grid h-10 w-10 shrink-0 place-items-center rounded-[var(--radius-surface)] border ${ICON_TONE[tone]}`}>
        <Icon name="bell" className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 className="text-[14px] font-bold leading-tight text-[var(--edify-text)]">{item.title}</h2>
          <span className={`${PILL} font-bold ${badgeClasses('neutral')}`}>{item.categoryLabel}</span>
          <span className={`${PILL} font-semibold ${badgeClasses(priorityPillTone(item.priority))}`}>{item.priorityLabel}</span>
          {item.actionRequired ? (
            <span className="inline-flex items-center rounded-full bg-[#b91c1c] px-1.5 py-0.5 text-[length:var(--edify-text-micro-size)] font-bold text-white">
              Action Required
            </span>
          ) : null}
        </div>
        {item.body ? <p className="max-w-4xl text-[13px] font-medium leading-relaxed text-[var(--edify-text-muted)]">{item.body}</p> : null}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-[length:var(--edify-text-micro-size)] font-semibold text-[var(--edify-text-subtle)]">
          <span className="whitespace-nowrap">{item.createdLabel}</span>
          {item.senderName ? <span className="whitespace-nowrap text-[var(--edify-text-muted)]">From {item.senderName}</span> : null}
          {item.contextType ? (
            <span className="flex min-w-0 items-center gap-1">
              Link: <strong className="min-w-0 break-all font-bold uppercase text-[var(--edify-text-muted)]">{item.contextType} ({item.contextId})</strong>
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex w-full shrink-0 flex-row-reverse flex-wrap items-center justify-between gap-2.5 pl-[3.25rem] sm:w-auto sm:flex-col sm:flex-nowrap sm:items-end sm:justify-start sm:pl-0">
        {href ? (
          <a
            href={href}
            className="flex h-8 items-center justify-center whitespace-nowrap rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-4 text-[12px] font-bold uppercase tracking-wider text-white shadow-sm"
          >
            {item.actionLabel}
          </a>
        ) : null}
        <div className="flex items-center gap-3 text-[length:var(--edify-text-micro-size)] font-bold text-[var(--edify-text-muted)]">
          {item.canMarkRead ? (
            <NotificationButton action={NotificationStatusAction.READ} id={item.id} className="inline-flex min-h-6 items-center whitespace-nowrap">
              Mark read
            </NotificationButton>
          ) : null}
          {item.canArchive ? (
            <NotificationButton action={NotificationStatusAction.ARCHIVE} id={item.id} className="inline-flex min-h-6 items-center hover:text-[#dc2626]">
              Archive
            </NotificationButton>
          ) : null}
        </div>
      </div>
    </li>
  );
}

export function NotificationList({ items, existingWebUrl }: { items: readonly NotificationItem[]; existingWebUrl: string }) {
  if (items.length === 0) {
    return (
      <div className="p-16 text-center" data-block="empty">
        <h2 className="text-[15px] font-bold">All caught up!</h2>
        <p className="mx-auto mt-1 max-w-xs text-[12px] font-semibold leading-relaxed text-[var(--edify-text-muted)]">
          No notifications match your current search criteria. You will be alerted when new workflow actions are dispatched.
        </p>
      </div>
    );
  }
  return (
    <ul className="divide-y divide-[var(--edify-border)]" aria-label="Notifications">
      {items.map((item) => (
        <Row key={item.id} item={item} existingWebUrl={existingWebUrl} />
      ))}
    </ul>
  );
}
