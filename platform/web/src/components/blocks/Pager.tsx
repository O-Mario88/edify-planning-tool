/*
 * The pager under a list: "Showing 1 to 50 of 699 schools", Prev, the page
 * numbers with gaps (the current one solid blue), Next. 50 rows a page is the
 * gateway's (owner, 2026-10-02). A list with a rows-a-page chooser has it at
 * the end (wider than a phone, as the existing page).
 */
import Link from 'next/link';

import type { PagePager } from '@/gen/edify/screens/v1/page_pb';

import { PageSize } from './PageSize';

const CONTROL =
  'edify-pagination__control min-h-11 min-w-11 px-2.5 rounded-control border border-slate-200 edify-surface edify-text-caption font-bold text-slate-600 hover:bg-slate-50 inline-flex items-center justify-center';
const CURRENT =
  'edify-pagination__control edify-pagination__control--current min-h-11 min-w-11 px-2.5 rounded-control edify-primary-solid text-white edify-text-caption font-bold tabular-nums inline-flex items-center justify-center';

/** The page feed writes Prev and Next as pages of their own (PagePagerPage). */
const PREV = 'Prev';
const NEXT = 'Next';

export function Pager({ pager }: { pager: PagePager }) {
  const labelled = pager.pages.some((page) => page.label === PREV || page.label === NEXT);
  const numbers = pager.pages.filter((page) => page.label !== PREV && page.label !== NEXT);
  const currentIndex = numbers.findIndex((page) => page.current);
  const previous = labelled ? pager.pages.find((page) => page.label === PREV) : currentIndex > 0 ? numbers[currentIndex - 1] : undefined;
  const next = labelled ? pager.pages.find((page) => page.label === NEXT) : currentIndex >= 0 ? numbers[currentIndex + 1] : undefined;
  // The existing pager (templates/components/table_pager.html).
  return (
    <nav aria-label="Table pages" data-block="pager" className="edify-pagination flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-slate-100">
      <p className="edify-pagination__summary edify-text-caption font-semibold text-slate-400 tabular-nums">{pager.summary}</p>
      <div className="edify-pagination__controls flex items-center gap-1">
        {previous?.href ? (
          <Link href={previous.href} rel="prev" aria-label="Previous page" className={`${CONTROL} edify-pagination__control--direction`}>
            <span className="edify-pagination__direction-label">Prev</span>
            <span className="edify-pagination__direction-symbol" aria-hidden="true">
              ‹
            </span>
          </Link>
        ) : null}
        {numbers.map((page, index) =>
          page.current ? (
            <span key={index} aria-current="page" aria-label={`Page ${page.label}, current page`} className={CURRENT}>
              {page.label}
            </span>
          ) : page.href ? (
            <Link key={index} href={page.href} aria-label={`Page ${page.label}`} className={`${CONTROL} tabular-nums`}>
              {page.label}
            </Link>
          ) : (
            <span key={index} className="edify-pagination__ellipsis edify-text-caption font-bold text-slate-300 px-1" aria-hidden="true">
              {page.label}
            </span>
          ),
        )}
        {next?.href ? (
          <Link href={next.href} rel="next" aria-label="Next page" className={`${CONTROL} edify-pagination__control--direction`}>
            <span className="edify-pagination__direction-label">Next</span>
            <span className="edify-pagination__direction-symbol" aria-hidden="true">
              ›
            </span>
          </Link>
        ) : null}
        {pager.size ? (
          <span className="ml-2 max-sm:hidden">
            <PageSize size={pager.size} />
          </span>
        ) : null}
      </div>
    </nav>
  );
}
