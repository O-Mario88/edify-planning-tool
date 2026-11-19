'use client';

/*
 * A card that switches between parts of itself (Participation's Planned and
 * Completed), as the app draws it (PageBlocksView SegmentsCard): its title
 * bar, the segment switch that scrolls sideways when long, a caption, then
 * the open part.
 */
import { useState } from 'react';
import type { ReactNode } from 'react';

export interface PhoneSegment {
  readonly label: string;
  readonly count: string;
  readonly active: boolean;
  readonly body: ReactNode;
}

export function PhoneSegments({ title, subtitle, caption, segments }: { title: string; subtitle: string; caption: string; segments: readonly PhoneSegment[] }) {
  const [open, setOpen] = useState(Math.max(0, segments.findIndex((segment) => segment.active)));
  const titled = Boolean(title || subtitle);
  return (
    <section data-ph="card" aria-label={title || undefined}>
      {titled ? (
        <div data-ph="titlebar">
          <h2 data-ph="table-title">{title}</h2>
          {subtitle ? <span data-ph="table-subtitle">{subtitle}</span> : null}
        </div>
      ) : null}
      <div data-ph="switch-area" data-alone={titled ? undefined : true}>
        <div data-ph="switch" role="group" aria-label={title || 'Parts'}>
          {segments.map((segment, index) => (
            <button key={segment.label} type="button" data-ph="seg" aria-pressed={index === open} onClick={() => setOpen(index)}>
              {segment.label}
              {segment.count ? <span data-ph="count">{segment.count}</span> : null}
            </button>
          ))}
        </div>
        {caption ? <p data-ph="caption">{caption}</p> : null}
      </div>
      {segments[open]?.body}
    </section>
  );
}
