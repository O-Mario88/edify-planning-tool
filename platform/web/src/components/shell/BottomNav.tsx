'use client';

/*
 * The phone's bottom bar (components/mobile_bottom_nav.html): the gateway's
 * bottom destinations, then More, which opens the full menu. The open tab
 * follows the page in the browser: the shell's layout is not redrawn when a
 * link moves within it.
 */
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

import type { NavItem } from '@/gen/edify/screens/v1/navigation_pb';
import { safeIcon } from '@/lib/icon';

import { isCurrent } from './Sidebar';

export function BottomNav({ items, path, more }: { items: NavItem[]; path: string; more: ReactNode }) {
  const here = usePathname() ?? path;
  return (
    <nav aria-label="Primary navigation" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-[var(--edify-border)] bg-[var(--edify-topbar-bg)] pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
      {items.slice(0, 4).map((item) => {
        const active = isCurrent(item.url, here);
        return (
          <Link
            key={item.url}
            href={item.url}
            aria-current={active ? 'page' : undefined}
            className={`edify-nav-icon relative flex h-16 flex-col items-center justify-center gap-1 text-[12px] font-semibold ${active ? 'text-[var(--brand-primary)] before:absolute before:left-1/4 before:right-1/4 before:top-0 before:h-[3px] before:rounded-b before:bg-[var(--brand-primary)]' : 'text-[var(--edify-text)]'}`}
          >
            <span aria-hidden="true" className="grid h-6 w-6 place-items-center" dangerouslySetInnerHTML={{ __html: safeIcon(item.iconSvg) }} />
            <span className="truncate">{item.label}</span>
          </Link>
        );
      })}
      {more}
    </nav>
  );
}
