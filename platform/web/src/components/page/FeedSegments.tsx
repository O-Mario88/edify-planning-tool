'use client';

/*
 * A switch between parts drawn on the page itself (PageSegments:
 * Participation's Planned and Completed): a titled card, the segment pills
 * with their counts, the sentence under them, and the chosen part's blocks.
 * The parts arrive drawn (server components passed in); this only chooses
 * which one shows. Each part keeps its own ticks while hidden.
 */
import { useState } from 'react';
import type { ReactNode } from 'react';

export interface SegmentView {
  readonly label: string;
  readonly count: string;
  readonly active: boolean;
  readonly body: ReactNode;
}

export function FeedSegments({ title, subtitle, caption, segments }: { title: string; subtitle: string; caption: string; segments: readonly SegmentView[] }) {
  const [chosen, setChosen] = useState(() => Math.max(segments.findIndex((segment) => segment.active), 0));
  return (
    <section aria-label={title || undefined} data-block="segments" className="overflow-hidden rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-sm)]">
      {title || subtitle ? (
        <header className="flex flex-wrap items-center gap-2 bg-[var(--edify-surface-muted)] px-4 py-2">
          {title ? <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{title}</h2> : null}
          {subtitle ? <span className="ml-auto text-[length:var(--edify-text-label-size)] font-medium">{subtitle}</span> : null}
        </header>
      ) : null}
      <div className="px-4 pt-3">
        <div role="tablist" aria-label={title || 'Parts'} className="inline-flex min-h-8 rounded-[8px] bg-[var(--edify-surface-muted)]">
          {segments.map((segment, index) => (
            <button
              key={segment.label}
              type="button"
              role="tab"
              aria-selected={index === chosen}
              onClick={() => setChosen(index)}
              className={`flex h-8 items-center gap-2 px-3.5 text-[length:var(--edify-text-label-size)] first:rounded-l-[8px] last:rounded-r-[8px] ${index === chosen ? 'bg-[var(--edify-web-segment-active)] font-bold text-white' : 'font-semibold text-[var(--edify-text-muted)] hover:text-[var(--edify-text)]'}`}
            >
              <span>{segment.label}</span>
              {segment.count ? <span data-segment-count>{segment.count}</span> : null}
            </button>
          ))}
        </div>
        {caption ? <p className="mt-2 text-[length:var(--edify-text-label-size)] font-medium">{caption}</p> : null}
      </div>
      {segments.map((segment, index) => (
        <div key={segment.label} role="tabpanel" hidden={index !== chosen} className="space-y-3 p-3">
          {segment.body}
        </div>
      ))}
    </section>
  );
}
