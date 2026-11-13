'use client';

/*
 * The bar for ticked rows (activities/selection_bar.html): it shows once a
 * row is ticked, says how many, and offers the page's buttons
 * (PageSelection). While the drawers are the existing web's, a button opens
 * the same page there (a drawer is never fetched from here: some write when
 * opened), where the rows are ticked again and the drawer opens.
 *
 * The page's bar counts every tick on the page, floating at its foot; a
 * part's bar (an opened cluster card's schools) counts the ticks inside that
 * part and sits under it.
 */
import { useEffect, useState } from 'react';

import type { PageSelection } from '@/gen/edify/screens/v1/page_pb';

export function SelectionBar({ selection, pageHref, scopeId }: { selection: PageSelection; pageHref: string; scopeId?: string }) {
  const [ids, setIds] = useState<readonly string[]>([]);
  useEffect(() => {
    const read = () => {
      const root = scopeId ? document.getElementById(scopeId) : document;
      const ticked = root ? Array.from(root.querySelectorAll<HTMLInputElement>('input[data-pick]:checked')) : [];
      // The page's bar leaves an opened card's ticks to that card's own bar.
      const boxes = scopeId ? ticked : ticked.filter((box) => !box.closest('[data-record-open]'));
      // A calendar run draws one box a day, all the one tick: each id counts once.
      setIds([...new Set(boxes.map((box) => box.dataset.pick ?? '').filter(Boolean))]);
    };
    document.addEventListener('change', read);
    return () => document.removeEventListener('change', read);
  }, [scopeId]);
  if (!ids.length) return null;
  const place = scopeId
    ? 'flex rounded-[10px]'
    : 'fixed inset-x-4 bottom-24 z-40 mx-auto flex max-w-[40rem] rounded-[10px] shadow-lg lg:bottom-6';
  return (
    <div role="region" aria-label="Selected rows" data-block="selection" className={`${place} flex-wrap items-center gap-3 border border-[var(--brand-primary-border)] bg-[var(--edify-surface)] px-4 py-2.5`}>
      <span className="font-semibold">
        {ids.length} {selection.noun}
      </span>
      <div className="ml-auto flex flex-wrap gap-2">
        {selection.actions.map((action) => (
          <a
            key={action.label}
            href={pageHref}
            title="Opens in the existing web app"
            className="inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[length:var(--edify-text-label-size)] font-semibold hover:bg-[var(--brand-primary-soft)]"
          >
            {action.label}
          </a>
        ))}
      </div>
    </div>
  );
}
