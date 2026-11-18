'use client';

/*
 * Buttons that filter the page's rows in the browser (To-Do's categories and
 * priorities), as the existing web's chip rails and the app's PageChipsView
 * do. A row shows while every chosen chip is "all", the row has no key for
 * it, or the row's key is the chosen value (the app's isShownFor). Rows are
 * FeedList's, which carry their keys in data-list-row.
 */
import { useEffect, useRef, useState } from 'react';

import type { PageChips } from '@/gen/edify/screens/v1/page_pb';

/** Whether a row with keys shows when name is chosen as value. */
export function rowShows(keys: Readonly<Record<string, string>>, name: string, value: string): boolean {
  return value === 'all' || value === '' || keys[name] === undefined || keys[name] === value;
}

function rowKeys(row: Element): Record<string, string> {
  try {
    const parsed: unknown = JSON.parse(row.getAttribute('data-list-row') ?? '{}');
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function FeedChips({ chips }: { chips: PageChips }) {
  const [value, setValue] = useState(chips.value);
  const rail = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const page = rail.current?.closest('[data-page]') ?? document;
    page.querySelectorAll('[data-list-row]').forEach((row) => {
      (row as HTMLElement).hidden = !rowShows(rowKeys(row), chips.name, value);
    });
  }, [chips.name, value]);
  // The existing tab rail of buttons (data-edify-tablist, the To-Do page's
  // Category and Priority), drawn by the existing stylesheets.
  return (
    <div ref={rail} data-edify-tablist="" role="group" aria-label={chips.label || 'Filter'} data-block="chips" className="max-w-full">
      {chips.chips.map((chip) => (
        <button key={chip.value} type="button" data-edify-tab="" className="edify-tab" aria-pressed={chip.value === value} onClick={() => setValue(chip.value)}>
          {chip.label}
          {chip.count ? (
            <>
              {' '}
              <span data-edify-tab-count="">{chip.count}</span>
            </>
          ) : null}
        </button>
      ))}
    </div>
  );
}
