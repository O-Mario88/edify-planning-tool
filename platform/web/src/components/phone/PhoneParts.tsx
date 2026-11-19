/*
 * The parts a phone table shares with the page (PageTableView.tsx): the
 * table pager and the empty state. Drawn on the server or inside the table.
 */
import { Inbox } from 'lucide-react';

import type { PageAction, PagePager } from '@/gen/edify/screens/v1/page_pb';

/** The shared table pager: "Showing 1–50 of 51" and the page buttons. */
/** A pager with nothing to say: no summary and no pages. */
export function pagerEmpty(pager: PagePager): boolean {
  return pager.summary === '' && pager.pages.length === 0;
}

export function PhonePager({ pager, resolve, alone = false }: { pager: PagePager; resolve: (href: string) => string; alone?: boolean }) {
  if (pagerEmpty(pager)) return null;
  return (
    <nav data-ph="pager" data-alone={alone || undefined} aria-label="Pages">
      <span data-ph="pager-summary">{pager.summary}</span>
      <span data-ph="pager-pages">
        {pager.pages.map((page, index) =>
          page.href && !page.current ? (
            <a key={`${page.label}-${index}`} data-ph="page-button" href={resolve(page.href)} aria-label={/^\d+$/.test(page.label) ? `Page ${page.label}` : page.label}>
              {page.label}
            </a>
          ) : (
            <span key={`${page.label}-${index}`} data-ph="page-button" aria-current={page.current ? 'page' : undefined} data-gap={page.current ? undefined : true}>
              {page.label}
            </span>
          ),
        )}
      </span>
    </nav>
  );
}

/** The platform empty state; with a way out, one line with the link under it. */
export function PhoneEmpty({ message, action, hrefOf }: { message: string; action?: PageAction; hrefOf: (action: PageAction) => string }) {
  if (action) {
    return (
      <div data-ph="empty-line">
        <span>{message}</span>
        <a href={hrefOf(action)}>{action.label} →</a>
      </div>
    );
  }
  return (
    <div data-ph="empty">
      <span data-ph="empty-mark" aria-hidden="true">
        <Inbox size={18} />
      </span>
      <span>{message}</span>
    </div>
  );
}
