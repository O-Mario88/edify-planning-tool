/**
 * A page's phone reading drawn in the native app's design: figure tiles, the
 * segment rail with two tabs and More, three filters and More, record
 * tables with their foot, panels and lists, each as the app draws them
 * (mobile/src/ui/page). Answers are shaped as the gateway gives them.
 */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { GetPageResponseSchema } from '@/gen/edify/screens/v1/page_screen_pb';

import { NavItemSchema, NavSectionSchema } from '@/gen/edify/screens/v1/navigation_pb';
import { create } from '@bufbuild/protobuf';

import { PhoneBlocks } from './PhoneBlocks';
import { PhoneMore } from './PhoneMore';
import { PhonePage } from './PhonePage';
import { scaleOf } from './PhoneChart';
import { railChips } from './PhoneChips';
import { inRowFor } from './PhoneFilters';
import { railTabs } from './PhoneLinkTabs';
import { foldSegments } from './PhoneSegments';
import { phoneTone, tileColumns } from './tone';

// The menu leaves a desktop through the app router (LeaveOnDesktop).
vi.mock('next/navigation', () => ({
  usePathname: () => '/more',
  useRouter: () => ({ back: () => undefined, replace: () => undefined, refresh: () => undefined }),
}));

const DRAWER = 'http://localhost:8010/my-plan';

function draw(answer: JsonValue, selectable = false): string {
  const page = fromJson(GetPageResponseSchema, answer);
  return renderToStaticMarkup(<PhoneBlocks blocks={page.blocks} pagePath="/my-plan" drawerHref={DRAWER} selectable={selectable} />);
}

const MY_PLAN: JsonValue = {
  header: { eyebrow: 'My Work', title: 'My Plan', description: 'Everything you have planned.', actions: [{ key: 'export', label: 'Export', enabled: true, href: '/my-plan/export-drawer', drawer: true }] },
  blocks: [
    {
      linkTabs: {
        tabs: [
          { label: 'This Week', href: '?period=week' },
          { label: 'This Month', href: '?period=month' },
          { label: 'This FY', href: '?period=fy', active: true },
        ],
        beside: { key: 'calendar', label: 'Open Calendar', enabled: true, href: '/calendar' },
      },
    },
    {
      filters: {
        hidden: { period: 'fy' },
        filters: [
          { name: 'fy', label: 'Fiscal year', value: '2027', options: [{ value: '2027', label: 'FY 2027' }] },
          { name: 'quarter', label: 'Quarter', value: 'all', options: [{ value: 'all', label: 'All quarters' }] },
          { name: 'month', label: 'Month', value: 'all', options: [{ value: 'all', label: 'All months' }] },
          { name: 'district', label: 'District', value: 'wakiso', options: [{ value: 'all', label: 'All' }, { value: 'wakiso', label: 'Wakiso' }] },
        ],
      },
    },
    { strip: { title: 'My activities', metrics: [{ label: 'Overdue visits', value: '3', tone: 'danger', href: '?status=overdue' }, { label: 'Planned this week', value: '1', note: 'Mon to Sun' }] } },
    {
      table: {
        title: 'Returned — Needs Correction',
        count: '1',
        columns: [{ label: 'School Id' }, { label: 'School' }, { label: 'Visits', numeric: true }],
        rows: [{ tone: 'overdue', pickId: '41', cells: [{ text: 'SCH-1' }, { text: 'Kimenyedde Primary', href: '/schools/1/', strong: true }, { text: '2' }], details: [{ label: 'Cluster', value: 'Kira' }] }],
      },
    },
    { pager: { summary: 'Showing 1–1 of 1', pages: [{ label: '1', current: true }, { label: 'Next', href: '?page=2' }] } },
  ],
};

describe('a page on a phone', () => {
  it('draws figures as the app tiles: icon, figure, label, tone and link', () => {
    const html = draw(MY_PLAN);
    expect(html).toContain('data-ph="tiles"');
    expect(html).toContain('--ph-columns:2');
    expect(html).toMatch(/<a data-ph="tile" href="\/my-plan\?status=overdue"[^>]*>/);
    expect(html).toContain('<span data-ph="tile-value" data-ph-tone="alert">3</span>');
    expect(html).toContain('<span data-ph="tile-label">Planned this week</span>');
    expect(html).toContain('title="Mon to Sun"');
  });

  it('shows the first and the open tab, the rest under More, and the calendar beside', () => {
    const html = draw(MY_PLAN);
    expect(html).toContain('<a data-ph="seg" href="/my-plan?period=week">This Week</a>');
    expect(html).toContain('<a data-ph="seg" aria-current="page" href="/my-plan?period=fy">This FY</a>');
    expect(html).toContain('More <span data-ph="count">1</span>');
    expect(html).toContain('<a data-ph="menu-item" role="menuitem" href="/my-plan?period=month">This Month</a>');
    expect(html).toMatch(/<a data-ph="beside" href="[^"]*calendar[^"]*" aria-label="Open Calendar"/);
  });

  it('keeps three filters in the row and counts the set ones under More', () => {
    const html = draw(MY_PLAN);
    expect(html).toContain('<form data-ph="filters" aria-label="Filters" action="/my-plan" method="get">');
    expect(html).toContain('<input type="hidden" name="period" value="fy"/>');
    expect(html.match(/data-ph="filter"/g)).toHaveLength(3);
    expect(html).toContain('aria-label="More 1 filters, 1 set"');
    expect(html).toContain('More 1');
  });

  it('draws a record table as a spreadsheet on a phone, with its count, toned rows, details and the pager as its foot', () => {
    const html = draw(MY_PLAN, true);
    expect(html).toContain('<h2 data-ph="table-title">Returned — Needs Correction</h2>');
    expect(html).toContain('aria-label="1 listed"');
    expect(html).not.toContain('data-ph="rows"');
    expect(html).toContain('<tr data-row-tone="overdue">');
    expect(html).toContain('<input type="checkbox" data-pick="41" aria-label="Select Kimenyedde Primary"/>');
    expect(html).toContain('aria-label="Show the details of Kimenyedde Primary"');
    expect(html).toContain('<th scope="col" data-numeric="true">Visits</th>');
    // The pager after the table is drawn once, inside the table's card.
    expect(html.match(/data-ph="pager"/g)).toHaveLength(1);
    expect(html.indexOf('data-ph="pager"')).toBeGreaterThan(html.indexOf('data-ph="grid"'));
  });

  it('folds a table explanation under a chevron, closed until it is tapped', () => {
    const html = draw({ blocks: [{ table: { title: 'Planned and remaining', columns: [{ label: 'Part' }], rows: [{ cells: [{ text: 'Your visits' }] }], footnote: 'Your target is 560 visits a year.' } }] });
    expect(html).toMatch(/<details data-ph="explain"><summary data-ph="explain-toggle"><svg[^>]*data-ph="explain-chevron"[^>]*>.*?<\/svg><span>Explanation<\/span><\/summary><p data-ph="footnote">Your target is 560 visits a year\.<\/p><\/details>/);
    expect(html).not.toMatch(/<details[^>]* open/);
  });

  it('draws panels and lists as the app does, keeping the chips keys', () => {
    const html = draw({
      blocks: [
        { panel: { title: 'Details', items: [{ fields: { facts: [{ label: 'Cluster', value: 'Kira', href: '/clusters/4/' }] } }, { rows: { rows: [{ label: 'Visits', value: '12', tone: 'good' }] } }] } },
        { list: { title: 'Do next', count: '2 open', items: [{ title: 'Chase delivery', lines: ['Kyampisi Primary'], tone: 'caution', keys: { cat: 'Partner' }, actions: [{ label: 'Open', enabled: true, href: '/todos/1/' }] }] } },
      ],
    });
    expect(html).toContain('Cluster: <a href="/clusters/4/">Kira</a>');
    expect(html).toContain('<span data-ph="data-value" data-ph-tone="good">12</span>');
    expect(html).toContain('data-list-row="{&quot;cat&quot;:&quot;Partner&quot;}"');
    expect(html).toContain('<span data-ph="list-icon" data-ph-tone="caution" aria-hidden="true">');
    expect(html).toContain('aria-label="Open: Chase delivery"');
  });

  it('draws a switch card’s open part flat and ruled, its chips the app’s rail with More, no card inside the card', () => {
    const html = draw({
      blocks: [
        {
          segments: {
            segments: [
              {
                label: 'This Week',
                active: true,
                blocks: [
                  { panel: { title: 'What needs you now', badges: [{ text: '8 past due' }], items: [{ text: 'Past due plans' }] } },
                  {
                    chips: {
                      name: 'cat',
                      label: 'Which kind of plan',
                      value: 'all',
                      chips: [
                        { label: 'All Categories', value: 'all' },
                        { label: 'School Visits (6)', value: 'visits' },
                        { label: 'Trainings (0)', value: 'trainings' },
                        { label: 'Cluster Meetings (2)', value: 'meetings' },
                      ],
                    },
                  },
                ],
              },
              { label: 'Map', blocks: [] },
            ],
          },
        },
      ],
    });
    const body = html.slice(html.indexOf('data-ph="seg-body"'));
    expect(body).toContain('<section data-ph="panel-flat" aria-label="What needs you now">');
    expect(body).not.toContain('data-ph="card"');
    expect(body).not.toContain('data-edify-tablist');
    expect(body).toContain('<div data-ph="rail" role="group" aria-label="Which kind of plan">');
    expect(body).toContain('aria-pressed="true">All Categories</button>');
    expect(body).toContain('aria-label="More 2, Which kind of plan"');
  });

  it('draws no card for a pager with nothing to page, on the page or inside a switch card', () => {
    const empty = { pager: { summary: '', pages: [] } };
    expect(draw({ blocks: [empty] })).toBe('<div data-ph="blocks"></div>');
    const html = draw({ blocks: [{ segments: { segments: [{ label: 'Matrix', active: true, blocks: [empty, { pager: { summary: '1–20 of 42', pages: [{ label: '1', current: true }] } }] }] } }] });
    const body = html.slice(html.indexOf('data-ph="seg-body"'));
    expect(body).not.toContain('data-ph="card"');
    expect(body).toContain('<span data-ph="pager-summary">1–20 of 42</span>');
  });

  it('draws chips on the page as the app’s rail, not the existing tab rail', () => {
    const html = draw({ blocks: [{ chips: { name: 'cat', label: 'Category', value: 'all', chips: [{ label: 'All', value: 'all' }, { label: 'Planning', value: 'planning' }, { label: 'Partner', value: 'partner' }] } }] });
    expect(html).toContain('<div data-ph="rail" role="group" aria-label="Category">');
    expect(html).not.toContain('data-edify-tablist');
    expect(html).toContain('aria-label="More 1, Category"');
  });

  it('draws a record card with its tick, pills, facts and a way to open it', () => {
    const html = draw(
      {
        blocks: [
          {
            record: {
              title: 'Nakifuma Primary',
              href: '/schools/9/',
              badges: [{ text: 'Core', tone: 'info' }],
              facts: [{ label: 'District', value: 'Mukono' }, { label: 'Visits', value: '0/4', tone: 'caution' }],
              details: [{ panel: { title: 'Intervention scores', items: [{ text: 'No confirmed scores.' }] } }],
              pickId: '9',
            },
          },
        ],
      },
      true,
    );
    expect(html).toContain('<input type="checkbox" data-pick="9" aria-label="Select Nakifuma Primary"/>');
    expect(html).toContain('aria-label="Show details for Nakifuma Primary">Nakifuma Primary</button>');
    expect(html).toContain('<span data-ph="record-badge" data-ph-tone="info">Core</span>');
    expect(html).toContain('<span data-ph="details-fact" data-ph-tone="caution" data-plain="true">Visits: <b>0/4</b></span>');
    expect(html).toContain('Show details');
  });

  it('draws a chart as cut-out bars: the shortest value inside, a legend and the data list', () => {
    const html = draw({
      blocks: [{ chart: { title: 'SSA score', axisTitle: 'SSA score (0–10)', categories: ['Leadership'], series: [{ name: 'FY 2025/26', values: [5] }, { name: 'FY 2026/27', values: [3.6] }] } }],
    });
    expect(html).toContain('<span data-ph="chart-key">');
    expect(html).toContain('role="img" aria-label="Leadership: 5 FY 2025/26, 3.6 FY 2026/27"');
    expect(html).toMatch(/data-ph="chart-bar" data-light="true" style="--ph-shade:33%;--ph-share:0.6">3.6<\/span>/);
    expect(html).toContain('<span data-ph="chart-unit">SSA score (0–10)</span>');
    expect(html).toContain('View chart data');
  });

  it('says once that a chart with nothing in it has nothing yet', () => {
    const html = draw({ blocks: [{ chart: { title: 'Visits', categories: ['Jul', 'Aug'], series: [{ name: 'Done', values: [0, 0] }] } }] });
    expect(html).toContain('Nothing recorded for this period yet.');
    expect(html).not.toContain('data-ph="chart-bar"');
  });

  it('puts Export beside the title in the header', () => {
    const page = fromJson(GetPageResponseSchema, MY_PLAN);
    const html = renderToStaticMarkup(<PhonePage answer={page} pagePath="/my-plan" drawerHref={DRAWER} />);
    expect(html).toContain('<p data-ph="eyebrow">My Work</p>');
    expect(html).toMatch(/<div data-ph="title-row"><h1 data-ph="title">My Plan<\/h1><a data-ph="export"/);
  });
});

describe('the phone menu behind More', () => {
  it('draws the account, the roles to work as, the reader’s sections as rows, and Sign out', () => {
    const sections = [create(NavSectionSchema, { label: 'Daily', items: [create(NavItemSchema, { label: 'My Plan', url: '/my-plan' }), create(NavItemSchema, { label: 'Smart Route Planner', url: '/my-plan/smart-route' })] })];
    const html = renderToStaticMarkup(<PhoneMore name="Paul N." email="cceo@edify.org" activeRole="CCEO" roles={['CCEO', 'Program Lead']} sections={sections} />);
    expect(html).toContain('<p data-ph="more-meta">CCEO · cceo@edify.org</p>');
    expect(html).toContain('<input type="hidden" name="role" value="Program Lead"/>');
    expect(html).toContain('<h2 data-ph="more-label">Daily</h2>');
    expect(html).toMatch(/<a data-ph="more-row" href="\/my-plan\/smart-route">.*Smart Route Planner/);
    expect(html).toContain('<form data-ph="more-form" action="/auth/sign-out" method="post">');
  });
});

describe('the phone rules', () => {
  it('keeps the first tab and the open one on the rail', () => {
    const tabs = [{ label: 'A' }, { label: 'B' }, { label: 'C', active: true }, { label: 'D' }].map((tab) => ({ href: tab.label, active: false, ...tab }));
    const { shown, rest } = railTabs(tabs as never);
    expect(shown.map((tab) => tab.label)).toEqual(['A', 'C']);
    expect(rest.map((tab) => tab.label)).toEqual(['B', 'D']);
  });

  it('keeps the first chip and the chosen one on a chips rail', () => {
    const chips = ['all', 'visits', 'trainings', 'meetings'].map((value) => ({ label: value, value, count: '' }));
    expect(railChips(chips as never, 'all').shown.map((chip) => chip.value)).toEqual(['all', 'visits']);
    const { shown, rest } = railChips(chips as never, 'meetings');
    expect(shown.map((chip) => chip.value)).toEqual(['all', 'meetings']);
    expect(rest.map((chip) => chip.value)).toEqual(['visits', 'trainings']);
  });

  it('holds three filters in a row, two on a narrow phone', () => {
    expect(inRowFor(358)).toBe(2);
    expect(inRowFor(479)).toBe(2);
    expect(inRowFor(480)).toBe(3);
    expect(inRowFor(720)).toBe(3);
    expect(inRowFor(0)).toBe(3);
  });

  it('keeps the first part and the open one on a folded switch, then the open one alone', () => {
    expect(foldSegments(4, 0)).toEqual({ shown: [0, 1], rest: [2, 3] });
    expect(foldSegments(6, 4)).toEqual({ shown: [0, 4], rest: [1, 2, 3, 5] });
    expect(foldSegments(4, 0, 2)).toEqual({ shown: [0], rest: [1, 2, 3] });
    expect(foldSegments(4, 2, 2)).toEqual({ shown: [2], rest: [0, 1, 3] });
  });

  it('sets tiles two a row on a phone and in even rows of at most five wider', () => {
    expect(tileColumns(1, false)).toBe(1);
    expect(tileColumns(7, false)).toBe(2);
    expect(tileColumns(7, true)).toBe(4);
    expect(tileColumns(10, true)).toBe(5);
    expect(tileColumns(3, true)).toBe(3);
  });

  it('ends a chart scale on a round figure at or above the largest value', () => {
    expect(scaleOf({ series: [{ values: [7.2] }], max: 10 } as never)).toEqual({ max: 10, step: 2 });
    expect(scaleOf({ series: [{ values: [214, 77] }], max: 0 } as never)).toEqual({ max: 300, step: 100 });
    expect(scaleOf({ series: [{ values: [0] }], max: 0 } as never)).toEqual({ max: 1, step: 1 });
  });

  it('reads the server tones as the app does', () => {
    expect(phoneTone('danger')).toBe('alert');
    expect(phoneTone('success')).toBe('good');
    expect(phoneTone('attention')).toBe('caution');
    expect(phoneTone('primary')).toBe('info');
    expect(phoneTone('plain')).toBeUndefined();
  });
});
