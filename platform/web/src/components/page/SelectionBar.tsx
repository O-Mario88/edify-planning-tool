'use client';

/*
 * The page's bar for ticked rows (activities/selection_bar.html): it shows
 * once a row is ticked, says how many, and offers the page's buttons
 * (PageSelection). While the drawers are the existing web's, a button opens
 * the same page there (a drawer is never fetched from here: some write when
 * opened), where the rows are ticked again and the drawer opens.
 */
import { useEffect, useState } from 'react';

import type { PageSelection } from '@/gen/edify/screens/v1/page_pb';

export function SelectionBar({ selection, pageHref }: { selection: PageSelection; pageHref: string }) {
  const [ids, setIds] = useState<readonly string[]>([]);
  useEffect(() => {
    const read = () =>
      setIds(Array.from(document.querySelectorAll<HTMLInputElement>('input[data-pick]:checked')).map((box) => box.dataset.pick ?? '').filter(Boolean));
    document.addEventListener('change', read);
    return () => document.removeEventListener('change', read);
  }, []);
  if (!ids.length) return null;
  return (
    <div role="region" aria-label="Selected rows" data-block="selection" className="fixed inset-x-4 bottom-24 z-40 mx-auto flex max-w-[40rem] flex-wrap items-center gap-3 rounded-[10px] border border-[var(--brand-primary-border)] bg-[var(--edify-surface)] px-4 py-2.5 shadow-lg lg:bottom-6">
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
