/**
 * The school profile (School 360) drawn from SchoolProfileService, which Go
 * answers (docs/migration/13-school-profiles.md): what the page asks with,
 * where its tabs lead, and the geometry of its bar charts. Presentation
 * only: every label, figure, tone and permission is the gateway's answer.
 */
import type { PageBlock, PageChart, PageLinkTabs, PageTab } from '@/gen/edify/screens/v1/page_pb';

/** The query keys the profile request carries; any other key is a view Go does not draw (a list a figure opens, `what=`). */
export const PROFILE_KEYS = ['tab', 'fy', 'period'] as const;

export interface ProfileAsk {
  readonly tab: string;
  readonly fy: string;
  readonly period: string;
  /** The address asks for something the profile request cannot carry (`what=…&key=…`): the existing web draws it. */
  readonly elsewhere: boolean;
}

/** The profile request a page query asks for (the query as pageQuery bounded it). */
export function profileAsk(query: Readonly<Record<string, string>>): ProfileAsk {
  const keys = Object.keys(query);
  return {
    tab: query.tab ?? '',
    fy: query.fy ?? '',
    period: query.period ?? '',
    elsewhere: keys.some((key) => !(PROFILE_KEYS as readonly string[]).includes(key)),
  };
}

/** The year the tab strip keeps: the year filter's value, else the one asked (partials/profiles/_tabs.html keeps `fy`, not the period). */
export function profileYear(blocks: readonly PageBlock[], asked: string): string {
  for (const block of blocks) {
    if (block.kind.case !== 'filters') continue;
    const year = block.kind.value.filters.find((filter) => filter.name === 'fy');
    if (year?.value) return year.value;
  }
  return asked;
}

/** The profile's tab strip as a link rail: each tab is `?tab=<key>&fy=<year>` on the profile's own path. */
export function profileTabs(tabs: readonly PageTab[], pagePath: string, fy: string): PageLinkTabs {
  return {
    $typeName: 'edify.screens.v1.PageLinkTabs',
    label: 'Profile sections',
    scrolls: true,
    tabs: tabs.map((tab) => ({
      $typeName: 'edify.screens.v1.PageLinkTab',
      label: tab.label,
      active: tab.active,
      href: `${pagePath}?${new URLSearchParams(fy ? { tab: tab.key, fy } : { tab: tab.key }).toString()}`,
    })),
  };
}

/** The profile's blocks split for its layout: the insights rail beside the rest on a wide screen, under it on a phone. */
export function splitRail(blocks: readonly PageBlock[]): { frame: PageBlock[]; main: PageBlock[]; rail: PageBlock[] } {
  const rail = blocks.filter((block) => block.kind.case === 'rail');
  if (!rail.length) return { frame: [], main: [...blocks], rail: [] };
  // The frame (scope line, facts, filters) runs the page's width above both columns.
  const frameKinds = new Set(['scopeLine', 'facts', 'filters']);
  let cut = 0;
  while (cut < blocks.length && frameKinds.has(blocks[cut]?.kind.case ?? '')) cut += 1;
  return { frame: blocks.slice(0, cut), main: blocks.slice(cut).filter((block) => block.kind.case !== 'rail'), rail };
}

/** Where the run of two or more titled cards that ends the blocks begins (the blocks' length where there is none). */
export function trailingPanels(blocks: readonly PageBlock[]): number {
  let start = blocks.length;
  while (start > 0 && blocks[start - 1]?.kind.case === 'panel') start -= 1;
  return blocks.length - start >= 2 ? start : blocks.length;
}

/** A chart's axis: from its floor to its ceiling (the largest value where it names none), ticks at round steps. */
export function chartAxis(chart: PageChart): { min: number; max: number; ticks: number[] } {
  const values = chart.series.flatMap((series) => series.values);
  const min = Math.min(chart.min, 0);
  const max = chart.max > min ? chart.max : Math.max(...values, min + 1);
  const span = max - min;
  const rough = span / 5;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((m) => m >= rough) ?? rough;
  const ticks: number[] = [];
  for (let tick = min; tick <= max + step / 1000; tick += step) ticks.push(Number(tick.toFixed(6)));
  return { min, max, ticks };
}

export interface BarPart {
  /** The series the part is coloured by (its index). */
  readonly series: number;
  /** Where the part starts and ends, as shares of the axis (0 to 1). */
  readonly from: number;
  readonly to: number;
  /** The value written on the part: inside the shorter bar, after the longer. */
  readonly value: number;
  readonly inside: boolean;
}

/**
 * One category's bar. Two series are a cut-out bar (owner, 2026-10-09: every
 * horizontal bar chart is a cut-out; chart-standard cutOut): the shorter
 * value drawn from the axis in its own colour with its figure inside, the
 * longer one's remainder after it with its figure beyond. One series is a
 * plain bar with its figure beyond.
 */
export function barParts(values: readonly number[], min: number, max: number): BarPart[] {
  const share = (value: number) => Math.min(Math.max((value - min) / (max - min), 0), 1);
  const present = values.map((value, series) => ({ value, series })).filter(({ value }) => Number.isFinite(value));
  if (present.length === 1) {
    const only = present[0]!;
    return [{ series: only.series, from: 0, to: share(only.value), value: only.value, inside: false }];
  }
  if (present.length !== 2) return [];
  const [first, second] = present as [{ value: number; series: number }, { value: number; series: number }];
  const [low, high] = first.value <= second.value ? [first, second] : [second, first];
  return [
    { series: low.series, from: 0, to: share(low.value), value: low.value, inside: true },
    { series: high.series, from: share(low.value), to: share(high.value), value: high.value, inside: false },
  ];
}

/** A chart value as the existing chart writes it (Chart.js: no trailing zeros). */
export function chartValue(value: number): string {
  return String(Number(value.toFixed(2)));
}
