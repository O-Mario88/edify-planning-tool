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
  return (
    <div ref={rail} role="group" aria-label={chips.label || 'Filter'} data-block="chips" className="flex flex-wrap gap-2">
      {chips.chips.map((chip) => {
        const chosen = chip.value === value;
        return (
          <button
            key={chip.value}
            type="button"
            aria-pressed={chosen}
            onClick={() => setValue(chip.value)}
            className={`flex h-9 items-center gap-2 rounded-full border px-4 text-[13px] font-semibold ${
              chosen
                ? 'border-[var(--edify-accent)] bg-[var(--edify-accent)] text-white'
                : 'border-[var(--edify-border)] bg-[var(--edify-card-surface)] text-[var(--edify-text)] hover:bg-[var(--brand-primary-soft)]'
            }`}
          >
            {chip.label}
            {chip.count ? <span className={chosen ? 'opacity-80' : 'text-[var(--edify-text-muted)]'}>{chip.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
