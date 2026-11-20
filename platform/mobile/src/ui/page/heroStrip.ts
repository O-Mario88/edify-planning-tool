/**
 * A page's hero figures, the one or two that decide the reader's work,
 * lifted out of the figure strips they arrive in into one strip that leads
 * the page and is drawn larger (owner, 2026-11-20, doc 181 §6.1: a
 * Programme Lead's dashboard leads with "Waiting on You" and "Visits Planned
 * Against Target"). A figure is moved, never copied, so nothing is counted
 * twice; a page with none of its heroes is left as it came. Pure, so it is
 * tested apart from the page; the web has the same rule
 * (platform/web/src/lib/heroStrip.ts).
 */
import { create } from '@bufbuild/protobuf';

import type { PageBlock, PageMetric } from '../../gen/edify/screens/v1/page_pb';
import { PageBlockSchema, PageStripSchema } from '../../gen/edify/screens/v1/page_pb';

/** Each page's hero figures, by the label the gateway gives them, in order. */
export const HERO_FIGURES_BY_PAGE: Readonly<Record<string, readonly string[]>> = {
  '/dashboard': ['Waiting on You', 'Visits Planned Against Target'],
};

/** The page's blocks with its heroes lifted into a strip of their own, and
 *  that strip's place (-1 when the page has none). */
export function liftHeroes(blocks: readonly PageBlock[], pagePath: string): { blocks: PageBlock[]; heroAt: number } {
  const labels = HERO_FIGURES_BY_PAGE[pagePath.replace(/\/+$/, '') || '/'] ?? [];
  if (labels.length === 0) return { blocks: [...blocks], heroAt: -1 };
  const found = new Map<string, PageMetric>();
  let first = -1;
  const rest = blocks.map((block, index) => {
    if (block.kind.case !== 'strip') return block;
    const strip = block.kind.value;
    const kept = strip.metrics.filter((m) => {
      if (!labels.includes(m.label) || found.has(m.label)) return true;
      found.set(m.label, m);
      if (first < 0) first = index;
      return false;
    });
    if (kept.length === strip.metrics.length) return block;
    return create(PageBlockSchema, { kind: { case: 'strip', value: create(PageStripSchema, { ...strip, metrics: kept }) } });
  });
  if (found.size === 0) return { blocks: rest, heroAt: -1 };
  const heroes = labels.flatMap((label) => (found.has(label) ? [found.get(label) as PageMetric] : []));
  const hero = create(PageBlockSchema, { kind: { case: 'strip', value: create(PageStripSchema, { metrics: heroes }) } });
  return { blocks: [...rest.slice(0, first), hero, ...rest.slice(first)], heroAt: first };
}

/** The figures a strip shows before "All figures" (owner, 2026-11-20: "reduce
 *  the number of kpi stats to the major used. other stats can be seen from
 *  the summary tables"). */
export const FIGURES_SHOWN = 4;

/** A figure with nothing to show yet: "Not measured", a dash, or blank. */
function unmeasured(value: string): boolean {
  const v = value.trim();
  return v === '' || v === '—' || v === '-' || /^not measured$/i.test(v);
}

/** A strip's figures split into the ones it shows, its first FIGURES_SHOWN
 *  measured figures in the gateway's order, and the ones folded under "All
 *  figures". A strip of FIGURES_SHOWN or fewer folds nothing. */
export function foldFigures<T extends { readonly value: string }>(figures: readonly T[]): { shown: T[]; folded: T[] } {
  if (figures.length <= FIGURES_SHOWN) return { shown: [...figures], folded: [] };
  const shown: T[] = [];
  const folded: T[] = [];
  for (const f of figures) {
    if (shown.length < FIGURES_SHOWN && !unmeasured(f.value)) shown.push(f);
    else folded.push(f);
  }
  return { shown, folded };
}
