/*
 * The top bar (templates/layouts/shell.html): page search, the date chip,
 * messages, notifications, report a problem, the theme switch and the
 * account menu.
 */
import type { ReactNode } from 'react';

import { dateChip } from '@/lib/today';

import { Icon } from './icons';
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

const ICON_LINK =
  'grid h-9 w-9 place-items-center rounded-full text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)] hover:text-[var(--edify-text)]';

export function TopBar({
  search,
  account,
  menu,
  existingWebUrl,
}: {
  search: PageSearch;
  account: AccountMenuProps;
  menu: ReactNode;
  existingWebUrl: string;
}) {
  const today = dateChip(new Date());
  const route = encodeURIComponent(account.path.split('?')[0] ?? '/');
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-[var(--edify-topbar-border)] bg-[var(--edify-topbar-bg)] px-4 shadow-[var(--edify-topbar-shadow)] backdrop-blur sm:px-[27px]">
      <PhoneMenu>{menu}</PhoneMenu>
      <HistoryControls />
      <form method="get" action={search.action} role="search" className="relative w-full max-w-[448px] flex-1">
        {Object.entries(search.keep).map(([name, value]) => (
          <input key={name} type="hidden" name={name} value={value} />
        ))}
        <label className="sr-only" htmlFor="topbar-search-input">
          {search.label ?? search.placeholder}
        </label>
        <input
          id="topbar-search-input"
          type="search"
          name="q"
          defaultValue={search.value}
          placeholder={search.placeholder}
          className="h-[38px] w-full rounded-[var(--radius-control)] border border-[var(--edify-field-border,#858e98)] bg-[var(--edify-surface)] py-[7px] pl-3 pr-[42px] text-[14px] font-semibold text-[var(--edify-text)] placeholder:font-medium placeholder:text-[var(--edify-text-subtle)] focus:border-[var(--brand-primary)] focus:outline-none"
        />
        <button
          type="submit"
          aria-label="Search"
          className="absolute right-[5px] top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full bg-[var(--brand-primary)] text-white"
        >
          <Icon name="search" className="h-4 w-4" strokeWidth={2.2} />
        </button>
      </form>
      <div className="ml-auto flex items-center gap-1.5">
        <span className="hidden items-center gap-1.5 whitespace-nowrap pr-2 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)] md:flex">
          <Icon name="calendar" className="h-[18px] w-[18px] text-[var(--brand-primary)]" />
          <span className="text-[length:var(--edify-text-micro-size)]">{today.weekday}</span>
          <span>{today.date}</span>
          <span className="rounded-full bg-[var(--brand-primary-soft)] px-2 py-0.5 text-[length:var(--edify-text-micro-size)] text-[var(--brand-primary-text)]">
            Week {today.week}
          </span>
        </span>
        <a href={`${existingWebUrl}/messages`} className={`${ICON_LINK} hidden sm:grid`} aria-label="Messages">
          <Icon name="messages" className="h-5 w-5" />
        </a>
        <a href={`${existingWebUrl}/notifications`} className={ICON_LINK} aria-label="Notifications">
          <Icon name="bell" className="h-5 w-5" />
        </a>
        <a href={`${existingWebUrl}/support?route=${route}`} className={`${ICON_LINK} hidden sm:grid`} aria-label="Report a problem with this page">
          <Icon name="alert" className="h-5 w-5" />
        </a>
        <ThemeToggle />
        <AccountMenu {...account} />
      </div>
    </header>
  );
}
