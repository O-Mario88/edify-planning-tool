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
  // A titled switch is a card (Participation's Planned & Completed); an
  // untitled one is the page's own view tabs (the Admin dashboard's
  // Operations and Map), its parts on the page itself.
  const titled = Boolean(title || subtitle);
  return (
    <section aria-label={title || undefined} data-block="segments" className={titled ? 'card p-0 overflow-hidden' : 'space-y-4'}>
      {title || subtitle ? (
        <header className="edify-table-titlebar flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-3">
          {title ? <h3>{title}</h3> : null}
          {subtitle ? <span className="tabular-nums">{subtitle}</span> : null}
        </header>
      ) : null}
      <div className={titled ? 'px-4 pt-3' : undefined}>
        <nav data-edify-tablist="" aria-label={title || 'Parts'}>
          {segments.map((segment, index) => (
            <button key={segment.label} type="button" data-edify-tab="" aria-pressed={index === chosen} onClick={() => setChosen(index)}>
              {segment.label}
              {segment.count ? (
                <>
                  {' '}
                  <span data-edify-tab-count="" data-segment-count="">
                    {segment.count}
                  </span>
                </>
              ) : null}
            </button>
          ))}
        </nav>
        {caption ? <p className="mt-2 edify-text-caption edify-text-muted">{caption}</p> : null}
      </div>
      {segments.map((segment, index) => (
        <div key={segment.label} role="tabpanel" hidden={index !== chosen} className={titled ? 'space-y-3 p-3' : 'space-y-4'}>
          {segment.body}
        </div>
      ))}
    </section>
  );
}
