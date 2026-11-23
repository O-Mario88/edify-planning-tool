import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import {
  PageBlockSchema,
  PageCellSchema,
  PageChartSchema,
  PageColumnSchema,
  PageFactSchema,
  PageFactsSchema,
  PageMetricSchema,
  PagePanelSchema,
  PageRailPartSchema,
  PageRailSchema,
  PageRowSchema,
  PageSeriesSchema,
  PageStripSchema,
  PageTableSchema,
} from '@/gen/edify/screens/v1/page_pb';
import type { PageBlock, PageRow } from '@/gen/edify/screens/v1/page_pb';

import { chartPoints, clusterFactsOf, clusterView, memberTypes, membersCsv, shownMembers } from './clusterProfileView';

const strip = (title: string): PageBlock =>
  create(PageBlockSchema, { kind: { case: 'strip', value: create(PageStripSchema, { title, metrics: [create(PageMetricSchema, { label: 'A', value: '1' })] }) } });
const panel = (title: string): PageBlock => create(PageBlockSchema, { kind: { case: 'panel', value: create(PagePanelSchema, { title }) } });
const chart = (title: string, categories: string[], values: number[], max = 100): PageBlock =>
  create(PageBlockSchema, { kind: { case: 'chart', value: create(PageChartSchema, { title, categories, max, series: [create(PageSeriesSchema, { name: 's', values })] }) } });

const COLUMNS = ['School ID', 'School Name', 'Type', 'SSA Avg', 'Last Visit', 'Actions'];
const columns = COLUMNS.map((label) => create(PageColumnSchema, { label }));
const row = (id: string, name: string, type: string, ssa: string, visit: string): PageRow =>
  create(PageRowSchema, { pickId: id, cells: [id, name, type, ssa, visit, ''].map((text) => create(PageCellSchema, { text })) });
const ROWS = [
  row('1', 'Bella Primary', 'Core', 'Not Assessed', 'Never'),
  row('2', 'Mother Thereza', 'Client', '6.20/10', '2026-04-22'),
  row('3', 'Quality Future', 'Client', '4.10/10', '2026-01-05'),
];
const ALL = { search: '', type: '', ssa: '', sort: 'name' } as const;

describe('clusterView', () => {
  it('finds each card by the title Go gave it', () => {
    const rail = create(PageBlockSchema, {
      kind: { case: 'rail', value: create(PageRailSchema, { title: 'SSA Performance', parts: [create(PageRailPartSchema, { key: 'ssa', figure: '4.57' })] }) },
    });
    const members = create(PageBlockSchema, { kind: { case: 'table', value: create(PageTableSchema, { title: 'Member Schools', columns }) } });
    const view = clusterView([
      strip('Cluster Summary'), rail, chart('SSA Trend', ['FY 2025/26'], [4.5], 10), panel('SSA Readiness by School'),
      strip('Cluster Activities'), strip('Meeting Attendance'), panel('Cluster Insights'), panel('Recommended Actions'), members,
    ]);
    expect(view.summary?.title).toBe('Cluster Summary');
    expect(view.ssa?.figure).toBe('4.57');
    expect(view.charts.map((item) => item.title)).toEqual(['SSA Trend']);
    expect(view.readiness?.title).toBe('SSA Readiness by School');
    expect(view.activities?.title).toBe('Cluster Activities');
    expect(view.attendance?.title).toBe('Meeting Attendance');
    expect(view.insights?.title).toBe('Cluster Insights');
    expect(view.recommended?.title).toBe('Recommended Actions');
    expect(view.members?.title).toBe('Member Schools');
    expect(view.others).toEqual([]);
  });

  it('keeps a block it has no place for', () => {
    const view = clusterView([panel('Something New')]);
    expect(view.others).toHaveLength(1);
  });
});

describe('clusterFactsOf', () => {
  it('splits the place from the people', () => {
    const block = create(PageBlockSchema, {
      kind: {
        case: 'facts',
        value: create(PageFactsSchema, {
          facts: ['District', 'Sub-county', 'Type', 'Status', 'CCEO', 'Programme Lead', 'Cluster Leader', 'Facilitating Partner'].map((label) => create(PageFactSchema, { label, value: label })),
        }),
      },
    });
    const { place, people } = clusterFactsOf([block]);
    expect(place.map((fact) => fact.label)).toEqual(['District', 'Sub-county', 'Type']);
    expect(people.map((fact) => fact.label)).toEqual(['CCEO', 'Programme Lead', 'Cluster Leader', 'Facilitating Partner']);
  });
});

describe('chartPoints', () => {
  it('reads the years Go sent and never makes one up', () => {
    const block = chart('Visit Coverage', ['FY 2025/26', 'FY 2026/27'], [57, 0]);
    expect(block.kind.case === 'chart' ? chartPoints(block.kind.value) : []).toEqual([{ label: 'FY 2025/26', value: 57 }, { label: 'FY 2026/27', value: 0 }]);
  });
});

describe('shownMembers', () => {
  const names = (rows: readonly PageRow[]) => rows.map((item) => item.cells[1]?.text);

  it('searches by name or School ID', () => {
    expect(names(shownMembers(ROWS, columns, { ...ALL, search: 'bella' }))).toEqual(['Bella Primary']);
    expect(names(shownMembers(ROWS, columns, { ...ALL, search: '3' }))).toEqual(['Quality Future']);
  });

  it('filters by type and by assessed or not', () => {
    expect(names(shownMembers(ROWS, columns, { ...ALL, type: 'Core' }))).toEqual(['Bella Primary']);
    expect(names(shownMembers(ROWS, columns, { ...ALL, ssa: 'assessed' }))).toEqual(['Mother Thereza', 'Quality Future']);
    expect(names(shownMembers(ROWS, columns, { ...ALL, ssa: 'not' }))).toEqual(['Bella Primary']);
  });

  it('sorts by score with the unassessed last, never as zero', () => {
    expect(names(shownMembers(ROWS, columns, { ...ALL, sort: 'ssa-low' }))).toEqual(['Quality Future', 'Mother Thereza', 'Bella Primary']);
    expect(names(shownMembers(ROWS, columns, { ...ALL, sort: 'ssa-high' }))).toEqual(['Mother Thereza', 'Quality Future', 'Bella Primary']);
  });

  it('sorts the longest since a visit first, with never visited at the top', () => {
    expect(names(shownMembers(ROWS, columns, { ...ALL, sort: 'visit' }))).toEqual(['Bella Primary', 'Quality Future', 'Mother Thereza']);
  });

  it('does not change the rows it was given', () => {
    const before = names(ROWS);
    shownMembers(ROWS, columns, { ...ALL, sort: 'ssa-low' });
    expect(names(ROWS)).toEqual(before);
  });
});

describe('memberTypes', () => {
  it('lists each school type once', () => {
    expect(memberTypes(ROWS, columns)).toEqual(['Client', 'Core']);
  });
});

describe('membersCsv', () => {
  it('writes the columns without the actions, quoted', () => {
    const csv = membersCsv(columns, [row('1', 'Hill, Primary', 'Core', '6.20/10', 'Never')]);
    expect(csv.split('\r\n')[0]).toBe('"School ID","School Name","Type","SSA Avg","Last Visit"');
    expect(csv.split('\r\n')[1]).toBe('"1","Hill, Primary","Core","6.20/10","Never"');
  });

  it('never lets a cell run as a spreadsheet formula', () => {
    const csv = membersCsv(columns, [row('1', '=HYPERLINK("x")', 'Core', '+1', '@a')]);
    expect(csv).toContain(`"'=HYPERLINK(""x"")"`);
    expect(csv).toContain(`"'+1"`);
    expect(csv).toContain(`"'@a"`);
  });
});
