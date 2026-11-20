/*
 * Tabs that are links, as the app draws them (PageLinkTabsView.tsx): the
 * segment rail with two tabs showing (the first and the open one), the rest
 * under "More n", and the link beside the rail as a square calendar button.
 * A workspace's sibling pages (`scrolls`) are a strip that scrolls sideways.
 */
import { CalendarDays } from 'lucide-react';

import type { PageLinkTab, PageLinkTabs } from '@/gen/edify/screens/v1/page_pb';
import { tabCount } from '@/lib/presentBlocks';

import { MorePanel } from './MorePanel';

/** The tabs a phone's rail shows: the first, and the open one (or the second). */
export function railTabs(tabs: readonly PageLinkTab[]): { shown: PageLinkTab[]; rest: PageLinkTab[] } {
  const open = tabs.findIndex((tab) => tab.active);
  const keep = new Set([0, open > 0 ? open : 1]);
  return { shown: tabs.filter((_, index) => keep.has(index)), rest: tabs.filter((_, index) => !keep.has(index)) };
}

/** A tab's words, with a count at its end drawn as its badge ("My activities 8"). */
function StripWords({ label }: { label: string }) {
  const { label: words, count } = tabCount(label);
  return (
    <>
      {words}
      {count ? <span data-ph="count">{count}</span> : null}
    </>
  );
}

interface PhoneLinkTabsProps {
  readonly tabs: PageLinkTabs;
  readonly resolve: (href: string) => string;
  /** Where the link beside the rail goes. */
  readonly besideHref?: string;
}

export function PhoneLinkTabs({ tabs, resolve, besideHref }: PhoneLinkTabsProps) {
  if (tabs.scrolls) {
    return (
      <nav data-ph="strip" aria-label={tabs.label || 'Pages'}>
        {tabs.label ? <span data-ph="strip-label">{tabs.label}</span> : null}
        {tabs.tabs.map((tab) => (
          <a key={tab.href} data-ph="strip-link" href={resolve(tab.href)} aria-current={tab.active ? 'page' : undefined}>
            <StripWords label={tab.label} />
          </a>
        ))}
      </nav>
    );
  }
  const { shown, rest } = railTabs(tabs.tabs);
  return (
    <div data-ph="rail-row">
      <nav data-ph="rail" aria-label={tabs.label || 'Views'}>
        {shown.map((tab) => (
          <a key={tab.href} data-ph="seg" aria-current={tab.active ? 'page' : undefined} href={resolve(tab.href)}>
            {tab.label}
          </a>
        ))}
        {rest.length > 0 ? (
          <MorePanel
            look="seg"
            label={`More ${rest.length} tabs`}
            words={
              <>
                More <span data-ph="count">{rest.length}</span>
              </>
            }
          >
            {rest.map((tab) => (
              <a key={tab.href} data-ph="menu-item" role="menuitem" href={resolve(tab.href)}>
                {tab.label}
              </a>
            ))}
          </MorePanel>
        ) : null}
      </nav>
      {tabs.beside && besideHref ? (
        <a data-ph="beside" href={besideHref} aria-label={tabs.beside.label} title={tabs.beside.label}>
          <CalendarDays size={16} aria-hidden="true" />
        </a>
      ) : null}
    </div>
  );
}
