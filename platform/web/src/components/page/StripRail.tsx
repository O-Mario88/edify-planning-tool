'use client';

/*
 * The figures' rail on a wide screen (static/js/kpi-strips.js): the cells keep
 * one row and scroll sideways; under them a track whose thumb is the part in
 * view, the range in view ("1–8 of 10") and "Swipe for more →", which moves
 * on by a screen (and back to the start from the end). Shown only while the
 * cells do not all fit. A phone draws the cells two a row instead.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { stripRange } from '@/lib/stripRange';

interface View {
  readonly overflow: boolean;
  readonly start: number;
  readonly end: number;
  readonly thumbWidth: number;
  readonly thumbOffset: number;
}

const NONE: View = { overflow: false, start: 0, end: 0, thumbWidth: 1, thumbOffset: 0 };

export function StripRail({ count, children }: { count: number; children: ReactNode }) {
  const rail = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>(NONE);
  const measure = useCallback(() => {
    const node = rail.current;
    const first = node?.querySelector('dl > div');
    if (!node || !first) return;
    const cell = first.getBoundingClientRect().width;
    const range = stripRange({ count, cell, width: node.clientWidth, scrollLeft: node.scrollLeft, scrollWidth: node.scrollWidth });
    setView(range ?? NONE);
  }, [count]);
  useEffect(() => {
    const node = rail.current;
    if (!node) return undefined;
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    schedule();
    node.addEventListener('scroll', schedule, { passive: true });
    const resize = new ResizeObserver(schedule);
    resize.observe(node);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      node.removeEventListener('scroll', schedule);
    };
  }, [measure]);
  const atEnd = view.end >= count;
  const advance = () => {
    const node = rail.current;
    if (!node) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    node.scrollTo({ left: atEnd ? 0 : node.scrollLeft + node.clientWidth, behavior: reduced ? 'instant' : 'smooth' });
  };
  return (
    <div>
      <div ref={rail} tabIndex={view.overflow ? 0 : -1} className="overflow-hidden rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-sm)] sm:overflow-x-auto sm:[scrollbar-width:none] sm:[&::-webkit-scrollbar]:hidden">
        {children}
      </div>
      {view.overflow ? (
        <div data-strip-rail className="max-sm:hidden">
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-[var(--edify-border)]">
            <span className="block h-full rounded-full bg-[var(--edify-text-subtle)]" style={{ width: `${view.thumbWidth * 100}%`, transform: `translateX(${view.thumbOffset * 100}%)` }} />
          </div>
          <div className="flex items-center justify-between gap-2 text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">
            <span aria-live="polite">{`${view.start}–${view.end} of ${count}`}</span>
            <button type="button" onClick={advance} aria-label={atEnd ? 'Show first metrics' : 'Show next metrics'} className="inline-flex min-h-8 items-center gap-1.5 font-semibold text-[var(--edify-text)]">
              {atEnd ? (
                <>
                  Back to start <span aria-hidden="true">←</span>
                </>
              ) : (
                <>
                  Swipe for more <span aria-hidden="true">→</span>
                </>
              )}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
