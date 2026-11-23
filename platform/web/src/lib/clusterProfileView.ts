/**
 * The Cluster Profile's layout, read from the gateway's page answer: which
 * card each block is, and how the member table is searched, sorted and
 * exported in the browser. Every figure is the gateway's.
 */
import type { PageBlock, PageChart, PageColumn, PageFact, PagePanel, PageRailPart, PageRow, PageStrip, PageTable } from '@/gen/edify/screens/v1/page_pb';

import type { TrendPoint } from './schoolProfileView';

export interface ClusterView {
  readonly summary: PageStrip | undefined;
  readonly ssa: PageRailPart | undefined;
  readonly ssaYear: string;
  readonly charts: readonly PageChart[];
  readonly readiness: PagePanel | undefined;
  readonly activities: PageStrip | undefined;
  readonly attendance: PageStrip | undefined;
  readonly insights: PagePanel | undefined;
  readonly recommended: PagePanel | undefined;
  readonly members: PageTable | undefined;
  readonly filters: readonly PageBlock[];
  /** Every other block, drawn after the cards so nothing Go sends is dropped. */
  readonly others: readonly PageBlock[];
}

export function clusterView(blocks: readonly PageBlock[]): ClusterView {
  const used = new Set<PageBlock>();
  const take = <T,>(pick: (block: PageBlock) => T | undefined): T | undefined => {
    for (const block of blocks) {
      if (used.has(block)) continue;
      const found = pick(block);
      if (found !== undefined) {
        used.add(block);
        return found;
      }
    }
    return undefined;
  };
  const stripNamed = (title: string) => take((block) => (block.kind.case === 'strip' && block.kind.value.title === title ? block.kind.value : undefined));
  const panelNamed = (title: string) => take((block) => (block.kind.case === 'panel' && block.kind.value.title === title ? block.kind.value : undefined));
  const summary = stripNamed('Cluster Summary');
  const rail = take((block) => (block.kind.case === 'rail' && block.kind.value.title === 'SSA Performance' ? block.kind.value : undefined));
  const readiness = panelNamed('SSA Readiness by School');
  const activities = stripNamed('Cluster Activities');
  const attendance = stripNamed('Meeting Attendance');
  const insights = panelNamed('Cluster Insights');
  const recommended = panelNamed('Recommended Actions');
  const members = take((block) => (block.kind.case === 'table' && block.kind.value.title === 'Member Schools' ? block.kind.value : undefined));
  const charts: PageChart[] = [];
  const filters: PageBlock[] = [];
  for (const block of blocks) {
    if (block.kind.case === 'chart' && ['SSA Trend', 'SSA Coverage', 'Visit Coverage', 'Training Coverage', 'Action Closure'].includes(block.kind.value.title)) {
      charts.push(block.kind.value);
      used.add(block);
    } else if (block.kind.case === 'filters') {
      filters.push(block);
      used.add(block);
    } else if (block.kind.case === 'facts') {
      used.add(block);
    }
  }
  return {
    summary,
    ssa: rail?.parts.find((part) => part.key === 'ssa'),
    ssaYear: rail?.subtitle ?? '',
    charts,
    readiness,
    activities,
    attendance,
    insights,
    recommended,
    members,
    filters,
    others: blocks.filter((block) => !used.has(block)),
  };
}

const PLACE = ['District', 'Sub-county', 'Type'] as const;
const PEOPLE = ['CCEO', 'Programme Lead', 'Cluster Leader', 'Facilitating Partner'] as const;

export function clusterFactsOf(blocks: readonly PageBlock[]): { place: PageFact[]; people: PageFact[] } {
  const facts = blocks.flatMap((block) => (block.kind.case === 'facts' ? block.kind.value.facts : []));
  const named = (labels: readonly string[]) => labels.flatMap((label) => facts.filter((fact) => fact.label === label));
  return { place: named(PLACE), people: named(PEOPLE) };
}

/** A history chart's points: only the years the gateway sent. */
export function chartPoints(chart: PageChart): TrendPoint[] {
  const values = chart.series[0]?.values ?? [];
  return chart.categories.flatMap((label, index) => {
    const value = values[index];
    return value === undefined || !Number.isFinite(value) ? [] : [{ label, value }];
  });
}

export interface MemberQuery {
  readonly search: string;
  readonly type: string;
  /** '', 'assessed' or 'not'. */
  readonly ssa: string;
  /** name, ssa-low, ssa-high or visit. */
  readonly sort: string;
}

const textAt = (row: PageRow, columns: readonly PageColumn[], label: string) => {
  const index = columns.findIndex((column) => column.label === label);
  return index < 0 ? '' : (row.cells[index]?.text ?? '');
};

/** A cell's score ("6.20/10"), or null for a school with none. */
const scoreOf = (text: string): number | null => {
  const value = Number.parseFloat(text);
  return Number.isFinite(value) ? value : null;
};

/** The roster as the reader has narrowed and ordered it; the rows given are left as they are. */
export function shownMembers(rows: readonly PageRow[], columns: readonly PageColumn[], query: MemberQuery): PageRow[] {
  const needle = query.search.trim().toLowerCase();
  const kept = rows.filter((row) => {
    const id = textAt(row, columns, 'School ID').toLowerCase();
    const name = textAt(row, columns, 'School Name').toLowerCase();
    if (needle && !id.includes(needle) && !name.includes(needle)) return false;
    if (query.type && textAt(row, columns, 'Type') !== query.type) return false;
    const assessed = scoreOf(textAt(row, columns, 'SSA Avg')) !== null;
    if (query.ssa === 'assessed' && !assessed) return false;
    if (query.ssa === 'not' && assessed) return false;
    return true;
  });
  const byName = (a: PageRow, b: PageRow) => textAt(a, columns, 'School Name').localeCompare(textAt(b, columns, 'School Name'));
  if (query.sort === 'ssa-low' || query.sort === 'ssa-high') {
    const direction = query.sort === 'ssa-low' ? 1 : -1;
    return [...kept].sort((a, b) => {
      const [left, right] = [scoreOf(textAt(a, columns, 'SSA Avg')), scoreOf(textAt(b, columns, 'SSA Avg'))];
      if (left === null && right === null) return byName(a, b);
      if (left === null) return 1; // a school with no score is never ranked as the lowest
      if (right === null) return -1;
      return (left - right) * direction || byName(a, b);
    });
  }
  if (query.sort === 'visit') {
    const day = (row: PageRow) => {
      const text = textAt(row, columns, 'Last Visit');
      return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : '';
    };
    return [...kept].sort((a, b) => day(a).localeCompare(day(b)) || byName(a, b));
  }
  return [...kept].sort(byName);
}

export function memberTypes(rows: readonly PageRow[], columns: readonly PageColumn[]): string[] {
  return [...new Set(rows.map((row) => textAt(row, columns, 'Type')).filter(Boolean))].sort();
}

/** A cell for a CSV: quoted, and unable to run as a formula when a spreadsheet opens it. */
const csvCell = (text: string) => {
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
};

/** The rows shown, as a CSV of every column but the row's actions. */
export function membersCsv(columns: readonly PageColumn[], rows: readonly PageRow[]): string {
  const kept = columns.map((column, index) => ({ column, index })).filter(({ column }) => column.label !== 'Actions');
  const head = kept.map(({ column }) => csvCell(column.label)).join(',');
  const lines = rows.map((row) => kept.map(({ index }) => csvCell(row.cells[index]?.text ?? '')).join(','));
  return [head, ...lines].join('\r\n');
}
