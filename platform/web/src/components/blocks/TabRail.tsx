/*
 * A segmented tab rail: straight dividers, only the outer ends curved, the
 * selected segment filled and never a pill; 32px segments, never wrapping
 * (owner, 2026-09-26 and 2026-10-02). A long rail scrolls sideways.
 */
import Link from 'next/link';

import type { PageLinkTabs } from '@/gen/edify/screens/v1/page_pb';

function PhoneMore({ rail, counts }: { rail: PageLinkTabs; counts?: readonly (number | undefined)[] }) {
  const others = rail.tabs.map((tab, index) => ({ tab, count: counts?.[index] })).filter(({ tab }) => !tab.active);
  if (!others.length) return null;
  return (
    <details className="relative sm:hidden">
      <summary className="flex h-8 cursor-pointer list-none items-center gap-2 rounded-r-[8px] bg-[var(--edify-surface-muted)] px-4 font-semibold">
        More <span className="grid h-6 min-w-6 place-items-center rounded-full bg-[var(--edify-border)] px-1.5 text-[12px]">{others.length}</span>
      </summary>
      <div className="absolute left-0 top-full z-30 mt-1 min-w-56 rounded-[var(--radius-surface)] border border-[var(--edify-border)] bg-[var(--edify-surface)] py-1 shadow-lg">
        {others.map(({ tab, count }) => (
          <Link key={tab.href} href={tab.href} className="flex justify-between gap-4 px-4 py-2 font-semibold hover:bg-[var(--edify-surface-muted)]">
            <span>{tab.label}</span>
            {count !== undefined ? <span>{count}</span> : null}
          </Link>
        ))}
      </div>
    </details>
  );
}

export function TabRail({ rail, counts }: { rail: PageLinkTabs; counts?: readonly (number | undefined)[] }) {
  return (
    <div className="flex sm:overflow-x-auto" data-block="tabs">
      <div role="tablist" aria-label={rail.label || undefined} className="inline-flex min-h-8 flex-nowrap items-stretch rounded-[8px] bg-[var(--edify-surface-muted)]">
        {rail.tabs.map((tab, index) => (
          <Link
            key={tab.href}
            href={tab.href}
            role="tab"
            aria-selected={tab.active}
            className={
              (tab.active ? '' : 'max-sm:hidden ') +
              'relative flex h-8 items-center gap-2 whitespace-nowrap px-3.5 text-[length:var(--edify-text-label-size)] leading-none first:rounded-l-[8px] last:rounded-r-[8px] ' +
              (tab.active
                ? 'z-10 bg-[var(--edify-web-segment-active)] font-bold text-white'
                : 'font-semibold text-[var(--edify-text-muted)] hover:text-[var(--edify-text)]') +
              (index > 0 && !tab.active && !rail.tabs[index - 1]?.active
                ? ' before:absolute before:bottom-2 before:left-0 before:top-2 before:w-px before:bg-[var(--edify-border)]'
                : '')
            }
          >
            <span>{tab.label}</span>
            {counts?.[index] !== undefined ? (
              <>
                {' '}
                <span data-tab-count>{counts[index]}</span>
              </>
            ) : null}
          </Link>
        ))}
      </div>
      <PhoneMore rail={rail} counts={counts} />
    </div>
  );
}
