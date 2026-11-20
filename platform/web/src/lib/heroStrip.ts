/**
 * A page's hero figures, the one or two that decide the reader's work,
 * lifted out of the figure strips they arrive in into one strip that leads
 * the page and is drawn larger (owner, 2026-11-20, doc 181 §6.1: a
 * Programme Lead's dashboard leads with "Waiting on You" and "Visits Planned
 * Against Target"). A figure is moved, never copied, so nothing is counted
 * twice; a page with none of its heroes is left as it came. Pure, so it is
 * tested apart from the page; the app has the same rule
 * (mobile/src/ui/page/heroStrip.ts).
 */
import { create } from '@bufbuild/protobuf';

import type { PageBlock, PageMetric } from '@/gen/edify/screens/v1/page_pb';
import { PageBlockSchema, PageStripSchema } from '@/gen/edify/screens/v1/page_pb';

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

/** A page whose figures in view are its planned work (owner, 2026-11-20:
 *  "it should show tiles based on what has been planned"): the figures with
 *  something planned, in the owner's order, up to FIGURES_SHOWN with the
 *  always-shown ones; nothing planned shows `empty`. The rest fold.
 *  My Plan: the visit target first, then trainings, cluster meetings and the
 *  period counts; the completed share always. "Core Visits Scheduled" is the
 *  owner's second figure; the gateway sends no such figure yet, so it takes
 *  its place once one exists. */
export interface PlannedFirst {
  readonly order: readonly string[];
  readonly always: readonly string[];
  readonly empty: string;
}

export const PLANNED_FIRST_BY_PAGE: Readonly<Record<string, PlannedFirst>> = {
  '/my-plan': {
    order: [
      'School Visits Scheduled This Period',
      'Core Visits Scheduled',
      'Trainings Scheduled This Period',
      'Cluster Meetings Scheduled This Period',
      'My Activities Planned This Week',
      'My Activities Planned This Month',
      'My Activities Planned This Quarter',
      'My Activities Planned This Financial Year',
    ],
    always: ['My Completed Share of Planned Work'],
    empty: 'School Visits Scheduled This Period',
  },
};

/** Whether a figure counts something planned: a number above zero. */
function planned(value: string): boolean {
  const n = Number.parseFloat(value.replace(/,/g, ''));
  return Number.isFinite(n) && n > 0;
}

function plannedFirst<T extends { readonly value: string; readonly label: string }>(figures: readonly T[], rule: PlannedFirst): { shown: T[]; folded: T[] } {
  const room = FIGURES_SHOWN - rule.always.length;
  const byLabel = (label: string) => figures.filter((f) => f.label === label);
  let lead = rule.order.flatMap(byLabel).filter((f) => planned(f.value)).slice(0, room);
  if (lead.length === 0) lead = byLabel(rule.empty);
  const shown = [...lead, ...rule.always.flatMap(byLabel)];
  return { shown, folded: figures.filter((f) => !shown.includes(f)) };
}

/** A figure with nothing to show yet: "Not measured", a dash, or blank. */
function unmeasured(value: string): boolean {
  const v = value.trim();
  return v === '' || v === '—' || v === '-' || /^not measured$/i.test(v);
}

/** A strip's figures split into the ones it shows, its first FIGURES_SHOWN
 *  measured figures in the gateway's order, and the ones folded under "All
 *  figures". A strip of FIGURES_SHOWN or fewer folds nothing. */
export function foldFigures<T extends { readonly value: string; readonly label: string }>(
  figures: readonly T[],
  pagePath = '',
): { shown: T[]; folded: T[] } {
  const rule = PLANNED_FIRST_BY_PAGE[pagePath.replace(/\/+$/, '') || '/'];
  if (rule && figures.some((f) => rule.order.includes(f.label) || rule.always.includes(f.label))) {
    return plannedFirst(figures, rule);
  }
  if (figures.length <= FIGURES_SHOWN) return { shown: [...figures], folded: [] };
  const shown: T[] = [];
  const folded: T[] = [];
  for (const f of figures) {
    if (shown.length < FIGURES_SHOWN && !unmeasured(f.value)) shown.push(f);
    else folded.push(f);
  }
  return { shown, folded };
}
