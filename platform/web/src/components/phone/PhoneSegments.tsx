'use client';

/*
 * A card that switches between parts of itself (Participation's Planned and
 * Completed), as the app draws it (PageBlocksView SegmentsCard): its title
 * bar, the segment switch, a caption, then the open part. The switch never
 * scrolls sideways (the platform's tab rail rule): when its parts do not fit
 * the card, the first and the open one stay on it and the rest move under
 * "More n", as the app's chips and link tabs do; when even those two do not
 * fit, only the open one stays.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode, RefObject } from 'react';

import { MorePanel } from './MorePanel';

export interface PhoneSegment {
  readonly label: string;
  readonly count: string;
  readonly active: boolean;
  readonly body: ReactNode;
}

/** The parts a folded switch keeps on it: at fold 1 the first and the open
 *  one (or the second), at fold 2 the open one alone. */
export function foldSegments(count: number, open: number, fold: 1 | 2 = 1): { shown: number[]; rest: number[] } {
  const keep = new Set(fold === 2 ? [open] : [0, open > 0 ? open : 1]);
  const all = Array.from({ length: count }, (_, index) => index);
  return { shown: all.filter((index) => keep.has(index)), rest: all.filter((index) => !keep.has(index)) };
}

type Fold = 0 | 1 | 2;

/** How far a switch must fold: measured after each layout, one step at a
 *  time, and again from whole when the card's width changes. */
function useFold(): { fold: Fold; switchRef: RefObject<HTMLDivElement | null> } {
  const [fold, setFold] = useState<Fold>(0);
  const switchRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = switchRef.current;
    if (el && fold < 2 && el.scrollWidth > el.clientWidth + 1) setFold((fold + 1) as Fold);
  }, [fold]);
  useEffect(() => {
    const area = switchRef.current?.parentElement;
    if (!area || typeof ResizeObserver === 'undefined') return undefined;
    let width = area.clientWidth;
    const watch = new ResizeObserver(() => {
      if (area.clientWidth === width) return;
      width = area.clientWidth;
      setFold(0);
    });
    watch.observe(area);
    return () => watch.disconnect();
  }, []);
  return { fold, switchRef };
}

export function PhoneSegments({ title, subtitle, caption, segments }: { title: string; subtitle: string; caption: string; segments: readonly PhoneSegment[] }) {
  const [open, setOpen] = useState(Math.max(0, segments.findIndex((segment) => segment.active)));
  const { fold, switchRef } = useFold();
  const titled = Boolean(title || subtitle);
  const all = segments.map((_, index) => index);
  const { shown, rest } = fold ? foldSegments(segments.length, open, fold) : { shown: all, rest: [] as number[] };
  return (
    <section data-ph="card" aria-label={title || undefined}>
      {titled ? (
        <div data-ph="titlebar">
          <h2 data-ph="table-title">{title}</h2>
          {subtitle ? <span data-ph="table-subtitle">{subtitle}</span> : null}
        </div>
      ) : null}
      <div data-ph="switch-area" data-alone={titled ? undefined : true}>
        <div ref={switchRef} data-ph="switch" data-folded={fold || undefined} role="group" aria-label={title || 'Parts'}>
          {shown.map((index) => {
            const segment = segments[index] as PhoneSegment;
            return (
              <button key={segment.label} type="button" data-ph="seg" aria-pressed={index === open} onClick={() => setOpen(index)}>
                {segment.label}
                {segment.count ? <span data-ph="count">{segment.count}</span> : null}
              </button>
            );
          })}
          {rest.length > 0 ? (
            // Keyed by the open part, so choosing from the menu closes it.
            <MorePanel
              key={open}
              look="seg"
              label={`More parts, ${rest.length}`}
              words={
                <>
                  More <span data-ph="count">{rest.length}</span>
                </>
              }
            >
              {rest.map((index) => {
                const segment = segments[index] as PhoneSegment;
                return (
                  <button key={segment.label} type="button" data-ph="menu-item" role="menuitem" onClick={() => setOpen(index)}>
                    {segment.label}
                    {segment.count ? ` ${segment.count}` : ''}
                  </button>
                );
              })}
            </MorePanel>
          ) : null}
        </div>
        {caption ? <p data-ph="caption">{caption}</p> : null}
      </div>
      {/* The open part's blocks, ruled one from the next inside this card. */}
      <div data-ph="seg-body">{segments[open]?.body}</div>
    </section>
  );
}
