/*
 * The top bar, in the existing web's markup and class names
 * (templates/layouts/shell.html), drawn by its own stylesheets: page
 * history, the page's search, today's date and week, messages,
 * notifications, report a problem, the theme switch and the account menu.
 */
import Link from 'next/link';

import { badgeCount } from '@/lib/badgeCount';
import { dateChip } from '@/lib/today';

import { AccountMenu, HistoryControls, PhoneMenu, ThemeToggle } from './TopBarControls';
import type { AccountMenuProps } from './TopBarControls';

export interface PageSearch {
  readonly action: string;
  readonly placeholder: string;
  /** What the field searches, for screen readers. */
  readonly label?: string;
  readonly value: string;
  /** The page's other query parameters, kept when searching. */
  readonly keep: Readonly<Record<string, string>>;
}

/** The unread figures the top bar's Messages and Notifications carry. */
export interface TopBarCounts {
  readonly messages: number;
  readonly notifications: number;
}

/** A count over its icon (components.css .notification-badge). */
function CountBadge({ count }: { count: number }) {
  const text = badgeCount(count);
  if (!text) return null;
  return (
    <span data-count-badge className="notification-badge absolute top-1 right-1">
      {text}
    </span>
  );
}

const UTILITY = 'edify-topbar__icon-control edify-topbar__utility flex items-center justify-center relative focus:outline-none';

export function TopBar({
  search,
  account,
  counts = { messages: 0, notifications: 0 },
}: {
  search: PageSearch;
  account: AccountMenuProps;
  existingWebUrl?: string;
  counts?: TopBarCounts;
}) {
  const today = dateChip(new Date());
  const weekday = today.weekday.charAt(0) + today.weekday.slice(1).toLowerCase();
  const short = today.date.split(',')[0] ?? today.date;
  const route = encodeURIComponent(account.path.split('?')[0] || '/');
  return (
    <header className="edify-topbar shrink-0 relative z-10">
      <div className="edify-topbar__lead flex items-center gap-4 flex-1 min-w-0">
        <HistoryControls />
        <PhoneMenu />
        <search className="edify-topbar__search max-w-md w-full min-w-0 relative block" data-edify-has-submit="">
          <form method="get" action={search.action}>
            {Object.entries(search.keep).map(([name, value]) => (
              <input key={name} type="hidden" name={name} value={value} />
            ))}
            <label className="sr-only" htmlFor="global-search-input">
              {search.label ?? search.placeholder}
            </label>
            <input
              type="search"
              id="global-search-input"
              name="q"
              defaultValue={search.value}
              placeholder={search.placeholder}
              className="h-9 w-full rounded-control pl-4 text-[13px] font-normal focus:outline-none transition-all edify-surface-muted border edify-border edify-text"
            />
            <button type="submit" aria-label="Search" className="edify-search-submit">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </button>
          </form>
        </search>
      </div>
      <div className="edify-topbar__date edify-topbar__when" title="Today's date">
        <span className="sr-only">
          Today is {today.date}, week {today.week}
        </span>
        <svg className="edify-topbar__when-mark" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <rect x="3" y="5" width="18" height="16" rx="3" />
          <path strokeLinecap="round" d="M16 3v4M8 3v4M3 10h18" />
        </svg>
        <span className="edify-topbar__when-day" aria-hidden="true">
          <span className="edify-topbar__when-weekday">{weekday}</span> <span className="edify-topbar__date-short xl:hidden">{short}</span>
          <span className="edify-topbar__date-long hidden xl:inline">{today.date}</span>
        </span>
        <span className="edify-topbar__when-week" aria-hidden="true">
          <span className="xl:hidden">Wk</span>
          <span className="hidden xl:inline">Week</span> {today.week}
        </span>
      </div>
      <div className="edify-topbar__utilities flex items-center gap-2 shrink-0">
        <Link href="/messages" className={`${UTILITY} edify-topbar__utility--messages`} title="Messages" aria-label="Messages">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4-.8L3 20l1.3-3.9A7.97 7.97 0 013 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
          <CountBadge count={counts.messages} />
        </Link>
        <Link href="/notifications" className={`${UTILITY} edify-topbar__utility--notifications`} title="Notifications" aria-label="Notifications">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
            />
          </svg>
          <CountBadge count={counts.notifications} />
        </Link>
        <a
          href={`/support?route=${route}`}
          className="edify-topbar__icon-control edify-topbar__secondary-link flex items-center justify-center"
          title="Report a problem with this page"
          aria-label="Report a problem with this page"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" />
          </svg>
        </a>
        <ThemeToggle />
        <AccountMenu {...account} />
      </div>
    </header>
  );
}
