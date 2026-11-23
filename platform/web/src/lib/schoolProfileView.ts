/**
 * The School Profile's layout, read from SchoolProfileService's answer: which
 * button sits in the header row, which tile leads a card, where each Core
 * School card goes. Arrangement only: every figure, label, tone and
 * permission is the gateway's, and nothing here calculates one.
 */
import { create } from '@bufbuild/protobuf';

import { PageMetricSchema } from '@/gen/edify/screens/v1/page_pb';
import type { PageAction, PageBlock, PageFact, PageHeader, PageMetric, PagePanel, PageRailPart, PageStrip, PageTable } from '@/gen/edify/screens/v1/page_pb';

/** The header row's buttons, in the design's order; any other action opens from the Actions menu. */
export const HERO_ACTIONS = ['Edit Details', 'Schedule', 'Assign to Partner', 'Enter SSA Score', 'Add to Project', 'Close School'] as const;

export const PERFORMANCE_STRIP = 'Performance And Impact';
export const OPERATIONS_STRIP = 'Operations';
export const FINANCE_STRIP = 'Loans And Business Transformation';
export const INTERVENTION_TABLE = 'Best Performing And Struggling Intervention';
export const TREND_CHART = 'Annual SSA Progress';

export const PERFORMANCE_LEAD = ['Enrolment', 'SSA Score', 'Schools Assessed', 'Teachers Trained'] as const;
export const OPERATIONS_LEAD = ['Visits Completed', 'Trainings Completed', 'Online Trainings', 'Cluster Meetings Held'] as const;
export const FINANCE_LEAD = ['School Loans', 'Schools Funded', 'Disbursed', 'Business Transformation Cases'] as const;

const PLACE_FACTS = ['District', 'Sub-region', 'Sub-county'] as const;
const PEOPLE_FACTS = ['CCEO', 'Programme Lead', 'Fiscal Year'] as const;
const CHAMPION_TITLE = 'Champion Readiness: ';

export function splitHeroActions(actions: readonly PageAction[]): { row: PageAction[]; menu: PageAction[] } {
  const inRow = new Set<string>(HERO_ACTIONS);
  return {
    row: HERO_ACTIONS.flatMap((label) => actions.filter((action) => action.label === label)),
    menu: actions.filter((action) => !inRow.has(action.label)),
  };
}

export interface SchoolIdentity {
  readonly schoolId: string;
  /** "Core School", or the record's own words for a type that is not Core or Client; empty when not given. */
  readonly typeLabel: string;
  readonly status: string;
  readonly statusTone: string;
  readonly place: readonly PageFact[];
  readonly people: readonly PageFact[];
  readonly cluster: PageFact | undefined;
}

function factsOf(blocks: readonly PageBlock[]): readonly PageFact[] {
  for (const block of blocks) {
    if (block.kind.case === 'facts') return block.kind.value.facts;
  }
  return [];
}

function schoolType(type: string): string {
  return type === 'Core' || type === 'Client' ? `${type} School` : type;
}

export function schoolIdentity(header: PageHeader | undefined, blocks: readonly PageBlock[]): SchoolIdentity {
  const facts = factsOf(blocks);
  const fact = (label: string) => facts.find((item) => item.label === label);
  const named = (labels: readonly string[]) => labels.flatMap((label) => facts.filter((item) => item.label === label));
  const status = fact('Status');
  return {
    schoolId: fact('School ID')?.value || (header?.description ?? '').replace(/^School ID:\s*/, ''),
    typeLabel: schoolType(fact('Type')?.value ?? ''),
    status: status?.value ?? '',
    statusTone: status?.tone ?? '',
    place: named(PLACE_FACTS),
    people: named(PEOPLE_FACTS),
    cluster: fact('Cluster'),
  };
}

export function stripNamed(blocks: readonly PageBlock[], title: string): PageStrip | undefined {
  for (const block of blocks) {
    if (block.kind.case === 'strip' && block.kind.value.title === title) return block.kind.value;
  }
  return undefined;
}

/** A card's lead tiles in the design's order, and the strip's other figures, so none of them is lost. */
export function leadMetrics(strip: PageStrip | undefined, lead: readonly string[]): { lead: PageMetric[]; more: PageMetric[] } {
  if (!strip) return { lead: [], more: [] };
  const leading = new Set(lead);
  return {
    lead: lead.flatMap((label) => strip.metrics.filter((metric) => metric.label === label)),
    more: strip.metrics.filter((metric) => !leading.has(metric.label)),
  };
}

/** The longest note a tile writes under its figure; a longer one stays as the tile's hover text. */
const NOTE_ON_TILE = 24;

/** The line under a figure: its short helper, else its note when that is short enough for a tile. */
export function metricLine(metric: PageMetric): string {
  if (metric.helper) return metric.helper;
  return metric.note.length <= NOTE_ON_TILE ? metric.note : '';
}

const NOT_ASSESSED = 'Not Assessed';
const NOT_COMPARED = 'Not Compared';
const NO_PREVIOUS = /^previous 0(\s|$)/;
const BASELINE = /^baseline (\d+(?:\.\d+)?)/;
const NO_SCORE_ROW = /^(No intervention has|Only one intervention has)/;

function honestMetric(metric: PageMetric, assessed: boolean): PageMetric {
  if (metric.label !== 'SSA Score') return metric;
  const compared = (line: string) => (NO_PREVIOUS.test(line) ? NOT_COMPARED : line);
  return { ...metric, value: assessed ? metric.value : NOT_ASSESSED, helper: compared(metric.helper), note: compared(metric.note) };
}

function honestRailPart(part: PageRailPart, assessed: boolean): PageRailPart {
  if (part.key !== 'ssa') return part;
  const baseline = BASELINE.exec(part.figureNote)?.[1];
  const hasEarlier = baseline !== undefined && Number(baseline) !== 0;
  if (assessed) return baseline !== undefined && !hasEarlier ? { ...part, figureNote: `${NOT_COMPARED}: no earlier SSA` } : part;
  return {
    ...part,
    figure: NOT_ASSESSED,
    figureNote: hasEarlier ? `Last confirmed ${baseline} · ${NOT_COMPARED}` : NOT_COMPARED,
    meters: part.meters.map((meter) => ({ ...meter, value: '—', fraction: 0 })),
  };
}

function honestStanding(table: PageTable): PageTable {
  const at = (label: string) => table.columns.findIndex((column) => column.label === label);
  const intervention = at('Intervention');
  const blanks = new Map<number, string>([[at('Previous'), '—'], [at('Current'), '—'], [at('Change'), '—'], [at('Trend'), NOT_COMPARED]]);
  return {
    ...table,
    rows: table.rows.map((row) =>
      NO_SCORE_ROW.test(row.cells[intervention]?.text ?? '')
        ? { ...row, cells: row.cells.map((cell, index) => (blanks.has(index) ? { ...cell, text: blanks.get(index) ?? '' } : cell)) }
        : row,
    ),
  };
}

/**
 * The Overview with Go's placeholder zeros named for what they are. Go keeps
 * the existing page's 0.00 for a school with no confirmed SSA; a 0.00 reads as
 * a real result, so it is drawn as Not Assessed, and a comparison with no
 * earlier reading as Not Compared. Go's own Schools Assessed count decides.
 */
export function honestSsa(blocks: readonly PageBlock[]): PageBlock[] {
  const assessedCount = stripNamed(blocks, PERFORMANCE_STRIP)?.metrics.find((metric) => metric.label === 'Schools Assessed')?.value;
  const assessed = assessedCount !== '0';
  return blocks.map((block) => {
    if (block.kind.case === 'strip' && block.kind.value.title === PERFORMANCE_STRIP) {
      return { ...block, kind: { case: 'strip', value: { ...block.kind.value, metrics: block.kind.value.metrics.map((metric) => honestMetric(metric, assessed)) } } };
    }
    if (block.kind.case === 'rail') {
      return { ...block, kind: { case: 'rail', value: { ...block.kind.value, parts: block.kind.value.parts.map((part) => honestRailPart(part, assessed)) } } };
    }
    if (block.kind.case === 'table' && block.kind.value.title === INTERVENTION_TABLE) {
      return { ...block, kind: { case: 'table', value: honestStanding(block.kind.value) } };
    }
    return block;
  });
}

export interface TrendPoint {
  readonly label: string;
  readonly value: number;
}

/** The school's confirmed SSA average by year. A year with no reading is left out, never drawn as a zero. */
export function trendPoints(blocks: readonly PageBlock[]): TrendPoint[] {
  for (const block of blocks) {
    if (block.kind.case !== 'chart' || block.kind.value.title !== TREND_CHART) continue;
    const chart = block.kind.value;
    const values = chart.series[0]?.values ?? [];
    return chart.categories.flatMap((category, index) => {
      const value = values[index];
      if (value === undefined || !Number.isFinite(value)) return [];
      return [{ label: category.replace(/\s*\(\d+ schools?\)$/, ''), value }];
    });
  }
  return [];
}

/** A panel sentence as a row: "Cluster sessions: 0 of 0" is a label and its value; any other sentence stays whole. */
export function panelLine(text: string): { label: string; value: string } {
  const colon = text.indexOf(': ');
  if (colon <= 0) return { label: '', value: text };
  return { label: text.slice(0, colon), value: text.slice(colon + 2) };
}

const SUPPORT_TITLE = 'Recommended Support';
const INTERVENTION_MATRIX = 'Intervention Matrix';
const ALL_INTERVENTIONS = 'All interventions';
const READINESS_PREFIX = 'Readiness: ';
const PACKAGE_TARGETS = /Visits \d+\/(\d+) · Trainings \d+\/(\d+)/;
const HANDOVERS = /Partner hand-overs: \d+ not yet scheduled · (\d+) scheduled · (\d+) completed/;
const CHECK_WORDS: readonly (readonly [string, ChampionCheck['state']])[] = [['Met', 'met'], ['Not met', 'not'], ['Not judged', 'none']];

export interface CoreSchoolView {
  /** Champion Readiness in Go's words; empty when the answer has none. */
  readonly readiness: string;
  readonly metrics: readonly PageMetric[];
  readonly package: PagePanel | undefined;
  readonly participation: PagePanel | undefined;
  readonly outcomes: PagePanel | undefined;
  readonly support: PagePanel | undefined;
  readonly champion: PagePanel | undefined;
  /** Every other block of the tab, drawn after the cards so nothing Go sends is dropped. */
  readonly others: readonly PageBlock[];
}

export function coreSchoolView(blocks: readonly PageBlock[]): CoreSchoolView {
  const panelBlock = (matches: (title: string) => boolean) =>
    blocks.find((block) => block.kind.case === 'panel' && matches(block.kind.value.title));
  const panelOf = (block: PageBlock | undefined) => (block?.kind.case === 'panel' ? block.kind.value : undefined);
  const stripBlock = blocks.find((block) => block.kind.case === 'strip');
  const metrics = stripBlock?.kind.case === 'strip' ? stripBlock.kind.value.metrics : [];
  // Open recommendations arrive as a section heading followed by an untitled panel.
  const supportHeading = blocks.findIndex((block) => block.kind.case === 'section' && block.kind.value === SUPPORT_TITLE);
  const supportRecords = supportHeading >= 0 && blocks[supportHeading + 1]?.kind.case === 'panel' ? blocks[supportHeading + 1] : undefined;
  const placed = {
    package: panelBlock((title) => title === 'Package and Support'),
    participation: panelBlock((title) => title === 'Participation'),
    outcomes: panelBlock((title) => title === 'Outcomes'),
    support: supportRecords ?? panelBlock((title) => title === SUPPORT_TITLE),
    champion: panelBlock((title) => title.startsWith(CHAMPION_TITLE)),
  };
  const used = new Set<PageBlock | undefined>([stripBlock, ...Object.values(placed), supportHeading >= 0 ? blocks[supportHeading] : undefined]);
  const champion = panelOf(placed.champion);
  return {
    readiness: champion?.title.slice(CHAMPION_TITLE.length) || (metrics.find((metric) => metric.label === 'Champion Readiness')?.value ?? ''),
    metrics,
    package: panelOf(placed.package),
    participation: panelOf(placed.participation),
    outcomes: panelOf(placed.outcomes),
    support: panelOf(placed.support),
    champion,
    others: blocks.filter((block) => !used.has(block)),
  };
}

export interface InterventionRow {
  readonly name: string;
  readonly href: string;
  readonly previous: string;
  readonly current: string;
  readonly change: string;
  readonly changeTone: string;
  readonly status: string;
}

/** The SSA tab's intervention rows, without its all-interventions total. */
export function interventionRows(blocks: readonly PageBlock[]): InterventionRow[] {
  for (const block of blocks) {
    if (block.kind.case !== 'table' || block.kind.value.title !== INTERVENTION_MATRIX) continue;
    const { columns, rows } = block.kind.value;
    const at = (start: string) => columns.findIndex((column) => column.label.startsWith(start));
    const [previous, current, change, status] = [at('Previous'), at('Current'), at('Change'), at('Status')];
    return rows
      .filter((row) => row.cells[0]?.text !== ALL_INTERVENTIONS)
      .map((row) => ({
        name: row.cells[0]?.text ?? '',
        href: row.cells[0]?.href ?? '',
        previous: row.cells[previous]?.text ?? '',
        current: row.cells[current]?.text ?? '',
        change: row.cells[change]?.text ?? '',
        changeTone: row.cells[change]?.tone ?? '',
        status: row.cells[status]?.text ?? '',
      }));
  }
  return [];
}

const panelTexts = (panel: PagePanel | undefined): string[] =>
  (panel?.items ?? []).flatMap((item) => (item.kind.case === 'text' ? [item.kind.value] : []));

/** The Core tab's five figures, each read from what Go answered. */
export function coreFigures(view: CoreSchoolView, year: string, interventions: readonly InterventionRow[]): PageMetric[] {
  const figure = (label: string, value: string, helper: string) => create(PageMetricSchema, { label, value, helper });
  const pack = view.metrics.find((metric) => metric.label === 'Package');
  const champion = view.metrics.find((metric) => metric.label === 'Champion Readiness');
  const targets = PACKAGE_TARGETS.exec(pack?.helper ?? '');
  const handovers = panelTexts(view.package).map((line) => HANDOVERS.exec(line)).find(Boolean);
  const scored = interventions.filter((row) => Number.isFinite(Number.parseFloat(row.current))).length;
  return [
    figure('Programme Package', targets ? `${targets[1]} visits · ${targets[2]} trainings` : 'No Package', year ? `for ${year}` : ''),
    figure('Interventions', String(scored), 'scored this year'),
    champion ?? figure('Champion Readiness', view.readiness || '—', ''),
    figure('Partner Hand-overs', handovers ? `${handovers[1]} Scheduled` : '—', handovers ? `${handovers[2]} Completed` : ''),
    figure('Implementation Progress', targets ? (pack?.value ?? '—') : '—', targets ? (pack?.helper ?? '') : 'No Core plan this year'),
  ];
}

export interface ChampionCheck {
  readonly state: 'met' | 'not' | 'none';
  readonly text: string;
}

/** The Champion rule's three checks, as Go worded them ("Met: …", "Not met: …", "Not judged: …"). */
export function championChecks(panel: PagePanel | undefined): ChampionCheck[] {
  const lines = (panel?.items ?? []).flatMap((item) => (item.kind.case === 'links' ? item.kind.value.links.filter((link) => !link.href).map((link) => link.text) : []));
  return lines.flatMap((line): ChampionCheck[] => {
    for (const [word, state] of CHECK_WORDS) {
      if (line.startsWith(`${word}: `)) return [{ state, text: line.slice(word.length + 2) }];
    }
    return [];
  });
}

/** The school's planning readiness from its header badge, without the badge's label. */
export function readinessWord(badges: readonly string[]): string {
  const badge = badges.find((text) => text.startsWith(READINESS_PREFIX));
  return badge ? badge.slice(READINESS_PREFIX.length) : '';
}
