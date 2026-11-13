/*
 * The pager under a list: "Showing 1 to 50 of 699 schools", Prev, the page
 * numbers with gaps (the current one solid blue), Next. 50 rows a page is the
 * gateway's (owner, 2026-10-02).
 */
import Link from 'next/link';

import type { PagePager } from '@/gen/edify/screens/v1/page_pb';

const CONTROL = 'grid h-8 min-w-8 place-items-center rounded-[var(--radius-control)] px-2 text-[12px] font-bold';

/** The page feed writes Prev and Next as pages of their own (PagePagerPage). */
const PREV = 'Prev';
const NEXT = 'Next';

export function Pager({ pager }: { pager: PagePager }) {
  const labelled = pager.pages.some((page) => page.label === PREV || page.label === NEXT);
  const numbers = pager.pages.filter((page) => page.label !== PREV && page.label !== NEXT);
  const currentIndex = numbers.findIndex((page) => page.current);
  const previous = labelled ? pager.pages.find((page) => page.label === PREV) : currentIndex > 0 ? numbers[currentIndex - 1] : undefined;
  const next = labelled ? pager.pages.find((page) => page.label === NEXT) : currentIndex >= 0 ? numbers[currentIndex + 1] : undefined;
  return (
    <nav aria-label="Pages" data-block="pager" className="flex flex-col gap-3 border-t border-[var(--edify-border)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="whitespace-nowrap text-[12px] font-semibold text-[var(--edify-text-muted)]">{pager.summary}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {previous?.href ? (
          <Link href={previous.href} aria-label="Previous page" className={`${CONTROL} border border-[var(--edify-border)] px-3 text-[var(--edify-text)] hover:bg-[var(--brand-primary-soft)]`}>
            Prev
          </Link>
        ) : null}
        {numbers.map((page, index) =>
          page.current ? (
            <span key={index} aria-current="page" aria-label={`Page ${page.label}, current page`} className={`${CONTROL} bg-[var(--brand-primary)] text-white shadow-sm`}>
              {page.label}
            </span>
          ) : page.href ? (
            <Link key={index} href={page.href} className={`${CONTROL} text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)]`}>
              {page.label}
            </Link>
          ) : (
            <span key={index} aria-hidden="true" className="w-8 text-center font-bold text-[var(--edify-text-subtle)]">
              {page.label}
            </span>
          ),
        )}
        {next?.href ? (
          <Link href={next.href} aria-label="Next page" className={`${CONTROL} border border-[var(--edify-border)] px-3 text-[var(--edify-text)] hover:bg-[var(--brand-primary-soft)]`}>
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}
