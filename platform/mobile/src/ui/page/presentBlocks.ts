/**
 * How the page's parts are presented, where the existing feed hands them over
 * in a raw form (owner, 2026-11-20: "make it more professional"). Pure, so it
 * is tested apart from the page; the app has the same rule as the web (platform/web/src/lib/presentBlocks.ts).
 *
 * - A panel of nothing but counted links ("0 planned this week", "8 past due,
 *   any age") is a row of figures, drawn as the platform's figure tiles.
 * - Links that step through periods ("‹ Previous week" … "Next week ›") are
 *   one stepper control, not a column of underlined links.
 * - A tab whose label ends in its count ("My activities 8") is drawn with
 *   the count as a badge, as the existing web draws it.
 */
import { create } from '@bufbuild/protobuf';

import type { PageBlock, PageLink, PageMetric } from '../../gen/edify/screens/v1/page_pb';
import { PageBlockSchema, PageMetricSchema, PageStripSchema } from '../../gen/edify/screens/v1/page_pb';

/** A counted link: the figure, then its words. */
const COUNTED = /^(\d[\d,]*)\s+(\S.*)$/;

/** The fewest counted links that make a row of figures. */
const FIGURES_FROM = 2;

/** Upper-cases a label's first letter ("past due, any age" → "Past due, any age"). */
function sentenceCase(words: string): string {
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The links as figures, when every one is counted; null otherwise. */
export function countedFigures(links: readonly PageLink[]): PageMetric[] | null {
  if (links.length < FIGURES_FROM) return null;
  const figures: PageMetric[] = [];
  for (const link of links) {
    const match = COUNTED.exec(link.text.trim());
    if (!match || link.drawer) return null;
    // No note: the figure and its words say it all, so the tile draws no info mark.
    figures.push(create(PageMetricSchema, { value: match[1], label: sentenceCase(match[2] ?? ''), href: link.href }));
  }
  return figures;
}

/** Whether links step through periods: the first goes back (‹), the last forward (›). */
export function isStepper(links: readonly PageLink[]): boolean {
  if (links.length < 2) return false;
  const first = links[0]?.text.trim() ?? '';
  const last = links.at(-1)?.text.trim() ?? '';
  return first.startsWith('‹') && last.endsWith('›');
}

/** A stepper link's words without its arrow, and which way it goes. */
export function stepOf(link: PageLink): { readonly words: string; readonly way: 'back' | 'forward' | 'here' } {
  const text = link.text.trim();
  if (text.startsWith('‹')) return { words: text.slice(1).trim(), way: 'back' };
  if (text.endsWith('›')) return { words: text.slice(0, -1).trim(), way: 'forward' };
  return { words: text, way: 'here' };
}

/** Labels that end in a number that names the thing, not counts it. */
const NUMBERED = /(^|\s)(week|wk|q|term|phase|step|cycle|grade|primary|p|fy|year|day|level|round|cohort)$/i;

/** A tab's words and its count, when its label ends in one ("My activities 8"). */
export function tabCount(label: string): { readonly label: string; readonly count: number } {
  const match = /^(.*\S)\s+(\d{1,3})$/.exec(label.trim());
  if (!match || NUMBERED.test(match[1] ?? '')) return { label, count: 0 };
  return { label: match[1] ?? label, count: Number(match[2]) };
}

/** The page's blocks with a panel of counted links turned into a row of figure tiles. */
export function presentBlocks(blocks: readonly PageBlock[]): PageBlock[] {
  return blocks.map((block) => {
    if (block.kind.case !== 'panel') return block;
    const panel = block.kind.value;
    const only = panel.items.length === 1 ? panel.items[0] : undefined;
    if (!only || only.kind.case !== 'links' || panel.badges.length) return block;
    const figures = countedFigures(only.kind.value.links);
    if (!figures) return block;
    return create(PageBlockSchema, {
      group: block.group,
      kind: { case: 'strip', value: create(PageStripSchema, { title: panel.title, subtitle: panel.subtitle, metrics: figures }) },
    });
  });
}
