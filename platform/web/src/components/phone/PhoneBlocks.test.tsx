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
import { railTabs } from './PhoneLinkTabs';
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
    expect(html).toContain('aria-label="More filters, 1 set"');
    expect(html).toContain('More 1');
  });

  it('draws a record table with its count, toned rows, details and the pager as its foot', () => {
    const html = draw(MY_PLAN, true);
    expect(html).toContain('<h2 data-ph="table-title">Returned — Needs Correction</h2>');
    expect(html).toContain('aria-label="1 listed"');
    expect(html).toContain('<tr data-row-tone="overdue">');
    expect(html).toContain('<input type="checkbox" data-pick="41" aria-label="Select Kimenyedde Primary"/>');
    expect(html).toContain('aria-label="Show the details of Kimenyedde Primary"');
    expect(html).toContain('<th scope="col" data-numeric="true">Visits</th>');
    // The pager after the table is drawn once, inside the table's card.
    expect(html.match(/data-ph="pager"/g)).toHaveLength(1);
    expect(html.indexOf('data-ph="pager"')).toBeGreaterThan(html.indexOf('data-ph="grid"'));
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
