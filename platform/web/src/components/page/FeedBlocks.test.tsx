/**
 * The blocks Planning and My Plan answer with, drawn from answers shaped
 * as the Go gateway gives them (trimmed from what it answered on the
 * development database, 2026-11-13).
 */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { GetPageResponseSchema } from '@/gen/edify/screens/v1/page_screen_pb';

import { FeedBlocks } from './FeedBlocks';

const DRAWER = 'http://localhost:8185/planning?tab=client';

function draw(answer: JsonValue, pagePath = '/planning', selectable = true): string {
  const page = fromJson(GetPageResponseSchema, answer);
  return renderToStaticMarkup(<FeedBlocks blocks={page.blocks} pagePath={pagePath} drawerHref={DRAWER} selectable={selectable} />);
}

const PLANNING: JsonValue = {
  blocks: [
    { filters: { filters: [{ name: 'fy', label: 'Fiscal year', value: '2027', options: [{ value: '2026', label: 'FY 2026' }, { value: '2027', label: 'FY 2027' }] }] } },
    { strip: { title: 'Planning context', metrics: [{ label: 'Ready for Support', value: '91', note: 'Clustered & SSA active' }, { label: 'SSA-Informed Plans', value: '50%', helper: '2 of 4 need attention' }] } },
    { panel: { items: [{ text: 'Your FY2027 visits: 7 of 560 planned.' }] } },
    { linkTabs: { tabs: [{ label: 'Client Schools', href: '?tab=client', active: true }, { label: 'Core Schools', href: '?tab=core' }] } },
    {
      table: {
        columns: [{ label: 'ID' }, { label: 'School Name' }, { label: 'Cluster' }, { label: 'Actions' }],
        rows: [
          { cells: [{ text: 'Program Lead 1 · Paul N. 75 schools' }] },
          {
            cells: [
              { text: '1650' },
              { text: 'Central Division Church of Uganda Primary', href: '/schools/cmw9p7vrk008fvxekheps' },
              { text: 'Cluster A', href: '/clusters/cmw9p8e4900p50wekhe46' },
              { actions: [{ key: 'menu', label: 'Schedule', enabled: true, href: '/planning/schedule-modal?school_id=1650', drawer: true }] },
            ],
            pickId: '1650',
            details: [{ label: 'District', value: 'Mukono', href: '/districts/x' }],
            detailsHref: '/schools/cmw9p7vrk008fvxekheps',
          },
        ],
      },
    },
    { pager: { summary: 'Showing 1–15 of 75 schools', pages: [{ label: '1', href: '/planning?page=1&tab=client', current: true }, { label: '2', href: '/planning?page=2&tab=client' }, { label: 'Next', href: '/planning?page=2&tab=client' }] } },
  ],
};

describe('Planning blocks', () => {
  const html = draw(PLANNING);

  it('draws the blocks in the answer’s order', () => {
    const order = [...html.matchAll(/data-block="([a-z-]+)"/g)].map((match) => match[1]);
    expect(order).toEqual(['filters', 'strip', 'panel', 'tabs', 'table', 'pager']);
  });

  it('draws the filter with its selected value and the strip’s figures', () => {
    expect(html).toContain('aria-label="Fiscal year"');
    expect(html).toMatch(/<option value="2027" selected="">FY 2027<\/option>/);
    expect(html).toContain('Ready for Support');
    expect(html).toContain('>91<');
    expect(html).toContain('2 of 4 need attention');
  });

  it('puts the tabs’ bare queries on the page’s path, the selected one marked', () => {
    expect(html).toContain('href="/planning?tab=core"');
    expect(html).toMatch(/aria-selected="true"[^>]*href="\/planning\?tab=client"|href="\/planning\?tab=client"[^>]*aria-selected="true"/);
  });

  it('draws a group heading row across the table', () => {
    expect(html).toMatch(/<tr[^>]*data-heading="true"><th colSpan="6"[^>]*>Program Lead 1 · Paul N. 75 schools<\/th>/);
  });

  it('links every school name to its profile and gives the row a tick box', () => {
    expect(html).toContain('href="/schools/cmw9p7vrk008fvxekheps"');
    expect(html).toContain('data-pick="1650"');
    expect(html).toContain('aria-label="Actions for Central Division Church of Uganda Primary"');
  });

  it('draws the pager with its own Next', () => {
    expect(html).toContain('Showing 1–15 of 75 schools');
    expect(html).toMatch(/aria-label="Next page"[^>]*>Next<|href="\/planning\?page=2&amp;tab=client"[^>]*aria-label="Next page"/);
  });

  it('hides a filter with nothing to choose but still sends its value', () => {
    const lone = draw({ blocks: [{ filters: { filters: [{ name: 'district', label: 'District', value: 'All', options: [{ value: 'All', label: 'All Districts' }] }] } }] });
    expect(lone).not.toContain('<select');
    expect(lone).toContain('<input type="hidden" name="district" value="All"/>');
  });

  it('draws no tick boxes when the page has no bar', () => {
    expect(draw(PLANNING, '/planning', false)).not.toContain('data-pick');
  });
});

const MY_PLAN: JsonValue = {
  blocks: [
    { linkTabs: { tabs: [{ label: 'This Week', href: '?period=week' }, { label: 'This FY', href: '?period=fy', active: true }], beside: { key: 'beside', label: 'Open Calendar', primary: true, enabled: true, href: '/calendar' } } },
    {
      table: {
        title: 'Planned and remaining · FY 2027',
        subtitle: 'Readiness 75% · 0 schools held',
        columns: [{ label: 'Part of the plan' }, { label: 'Planned', numeric: true }, { label: 'Remaining', numeric: true }],
        rows: [{ cells: [{ text: 'Your visits' }, { text: '0' }, { text: '560', href: '?list=staff_visits_left#plan-list', tone: 'warning' }] }],
        footnote: 'Your target is 560 visits a year.',
      },
    },
    { table: { title: 'School Visits Planned for This FY', emptyMessage: 'No school visits planned for this period.', count: '0', emptyAction: { key: 'empty', label: 'Open Planning', enabled: true, href: '/planning' } } },
    { strip: { title: 'Plan Breakdown by Period', subtitle: 'All activity types combined', metrics: [{ label: 'This Week', value: '0 activities' }] } },
  ],
};

describe('My Plan blocks', () => {
  const html = draw(MY_PLAN, '/my-plan');

  it('draws Open Calendar beside the period tabs as the primary button', () => {
    expect(html).toContain('href="/my-plan?period=week"');
    expect(html).toMatch(/href="\/calendar"[^>]*data-action="beside"/);
    expect(html).toContain('Open Calendar');
  });

  it('draws the readiness table with its line, numeric columns, tones and note', () => {
    expect(html).toContain('Planned and remaining · FY 2027');
    expect(html).toContain('Readiness 75% · 0 schools held');
    expect(html).toMatch(/<th scope="col" class="[^"]*text-right[^"]*">Planned<\/th>/);
    expect(html).toContain('href="/my-plan?list=staff_visits_left#plan-list"');
    expect(html).toContain('text-[var(--edify-warning-text)]');
    expect(html).toContain('Your target is 560 visits a year.');
  });

  it('draws an empty table as its sentence and its way out, with the count', () => {
    expect(html).toContain('No school visits planned for this period.');
    expect(html).toMatch(/href="\/planning"[^>]*>Open Planning →<\/a>/);
    expect(html).toMatch(/data-count="true">0</);
  });

  it('shows a strip’s title only when it has a line under it', () => {
    expect(html).toContain('<h2 class="text-[length:var(--edify-text-title-size)] font-bold">Plan Breakdown by Period</h2>');
    expect(draw(PLANNING)).not.toContain('>Planning context</h2>');
  });
});

describe('record cards and kinds not drawn yet', () => {
  it('draws a cluster card with its link, pill, menu and facts', () => {
    const html = draw({
      blocks: [
        {
          record: {
            title: 'Cluster A',
            href: '/clusters/cmw9p8e4900p50wekhe46',
            badges: [{ text: 'Critical', tone: 'alert' }],
            actions: [{ key: 'menu', label: 'Schedule Cluster Meeting', enabled: true, href: '/planning/schedule-modal?cluster_id=x', drawer: true }],
            facts: [{ label: 'Avg SSA', value: '4.6/10', tone: 'alert' }],
          },
        },
      ],
    });
    expect(html).toContain('href="/clusters/cmw9p8e4900p50wekhe46"');
    expect(html).toContain('Critical');
    expect(html).toContain('aria-label="Actions for Cluster A"');
    expect(html).toContain('4.6/10');
  });

  it('gives a card that loads its schools an opener, closed until opened', () => {
    const html = draw({ blocks: [{ record: { title: 'Cluster A', href: '/clusters/a', detailsPath: '/partials/clusters/a/schools' } }] }, '/clusters');
    expect(html).toContain('aria-label="Show details for Cluster A"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain('data-record-open');
  });

  it('gives no opener to a card with nothing more, or a part not on the allow-list', () => {
    const html = draw({ blocks: [{ record: { title: 'Cluster B', detailsPath: '/clusters/b/bulk-assign-drawer' } }] }, '/clusters');
    expect(html).not.toContain('Show details for Cluster B');
  });

  it('sends a panel’s drawer link to the existing page, never to the drawer', () => {
    const html = draw(
      { blocks: [{ panel: { items: [{ text: 'No clusters found.' }, { links: { links: [{ text: 'Create Cluster', href: '/clusters/create-drawer', drawer: true }, { text: 'Open School Directory', href: '/schools' }] } }] } }] },
      '/clusters',
    );
    expect(html).toMatch(new RegExp(`<a href="${DRAWER.replace(/[?]/g, "\\?")}"[^>]*>Create Cluster</a>`));
    expect(html).not.toContain('create-drawer');
    expect(html).toContain('href="/schools"');
  });

  it('says so for a kind it does not draw', () => {
    expect(draw({ blocks: [{ chips: { name: 'cat', label: 'x' } }] })).toContain('not drawn here yet');
  });
});

vi.mock('next/navigation', () => ({
  usePathname: () => '/planning',
  useRouter: () => ({ push: () => undefined }),
  useSearchParams: () => new URLSearchParams('tab=client'),
}));

describe('Planning read whole (the coordinator review, 2026-11-13)', () => {
  const EMPTY: JsonValue = {
    blocks: [
      {
        filters: {
          filters: [{ name: 'fy', label: 'Fiscal year', caption: 'FY', value: '2027', options: [{ value: '2026', label: 'FY 2026' }, { value: '2027', label: 'FY 2027' }] }],
        },
      },
      { panel: { items: [{ text: 'Your FY2027 visits: 0 of 280 planned. Core 0 of 0 · Client 0 of 0.', lead: 'Your FY2027 visits: 0 of 280 planned.', tone: 'info' }] } },
      {
        panel: {
          items: [
            { text: 'No schools have been clustered yet.' },
            {
              text: 'Planning works on clustered schools. Every school is still in the School Directory — add them to a cluster and they appear here.',
              textLinks: [{ text: 'School Directory', href: '/schools' }],
            },
          ],
        },
      },
      {
        pager: {
          summary: 'Showing 0–0 of 0 schools',
          size: { name: 'per_page', label: 'Per page', value: '15', options: [{ value: '15', label: '15 / page' }, { value: '20', label: '20 / page' }] },
        },
      },
    ],
  };

  it('draws the short word over a filter and keeps its name for a screen reader', () => {
    const html = draw(EMPTY);
    expect(html).toContain('>FY</span>');
    expect(html).toContain('aria-label="Fiscal year"');
  });

  it('draws the workload line as a note with its bold opening and the rest', () => {
    const html = draw(EMPTY);
    expect(html).toContain('data-block="note"');
    expect(html).toContain('<strong class="font-bold">Your FY2027 visits: 0 of 280 planned.</strong> Core 0 of 0 · Client 0 of 0.');
  });

  it('keeps the empty state sentence whole around its link, with the pager and its size in the same card', () => {
    const html = draw(EMPTY);
    expect(html).toContain('No schools have been clustered yet.');
    expect(html).toMatch(/Every school is still in the <a [^>]*href="\/schools">School Directory<\/a>/);
    expect(html).toContain('School Directory</a> — add them to a cluster and they appear here.');
    const card = html.slice(html.indexOf('data-empty'));
    expect(card).toContain('Showing 0–0 of 0 schools');
    expect(card).toContain('15 / page');
    expect(html.match(/data-block="pager"/g)).toHaveLength(1);
  });
});

describe('plan-status and Visit Lock chips (web-fixes-2)', () => {
  const CHIPS: JsonValue = {
    blocks: [
      {
        table: {
          columns: [{ label: 'ID' }, { label: 'Visit Plan Status' }, { label: 'Training Plan Status' }, { label: 'Visit Lock' }],
          rows: [
            {
              cells: [
                { text: '1546' },
                { text: '1 Planned1 Complete', pills: [{ text: '1 Planned', tone: 'planned' }, { text: '1 Complete', tone: 'verified' }] },
                { text: 'Not Planned', pills: [{ text: 'Not Planned', tone: 'none' }] },
                { text: 'Staff visit scheduled', pills: [{ text: 'Staff visit scheduled', tone: 'closed', title: 'Kasawo has had its visit.', icon: 'lock' }] },
              ],
            },
            { cells: [{ text: '1598' }, { text: 'Not Planned', pills: [{ text: 'Not Planned', tone: 'none' }] }, { text: '—' }, { text: 'Unlocked', pills: [{ text: 'Unlocked', tone: 'open', icon: 'unlock' }] }] },
          ],
        },
      },
    ],
  };

  it('draws each chip in its own colour, never the words run together', () => {
    const html = draw(CHIPS);
    expect(html).not.toContain('1 Planned1 Complete');
    expect(html).toMatch(/data-planning-tone="planned"[^>]*bg-\[#fbbf24\][^>]*>1 Planned</);
    expect(html).toMatch(/data-planning-tone="verified"[^>]*success-light[^>]*>1 Complete</);
    expect(html.match(/data-planning-tone="none"[^>]*danger-light/g)).toHaveLength(2);
  });

  it('gives a held visit a shut padlock and its sentence, an unlocked one an open padlock', () => {
    const html = draw(CHIPS);
    expect(html).toMatch(/title="Kasawo has had its visit\." data-planning-tone="closed"[^>]*><svg[^>]*><path d="M4\.5 7V5/);
    expect(html).toMatch(/data-planning-tone="open"[^>]*bg-transparent[^>]*><svg[^>]*><path d="M10\.5 1\.5/);
  });
});

describe('filters the page folds under its own More filters (web-fixes-2)', () => {
  it('puts the Clusters page’s authored three under More and keeps the five in the row', () => {
    const select = (name: string, more = false) => ({ name, label: name, value: '', more, options: [{ value: '', label: 'All' }, { value: 'x', label: 'X' }] });
    const html = draw({
      blocks: [{ filters: { filters: [...['fy', 'quarter', 'district', 'sub_county', 'staff'].map((n) => select(n)), ...['ssa_status', 'cluster_risk', 'activity_status'].map((n) => select(n, true))] } }],
    }, '/clusters');
    const [row, more] = html.split('aria-label="More filters"');
    for (const name of ['fy', 'quarter', 'district', 'sub_county', 'staff']) expect(row).toContain(`name="${name}"`);
    for (const name of ['ssa_status', 'cluster_risk', 'activity_status']) {
      expect(row).not.toContain(`name="${name}"`);
      expect(more).toContain(`name="${name}"`);
    }
  });
});

describe('a record card’s facts in the existing card’s colours (web-fixes-2)', () => {
  it('draws plain values in the accent blue and toned ones in the card’s red, amber and green', () => {
    const html = draw({
      blocks: [
        {
          record: {
            title: 'Cluster A',
            facts: [
              { label: 'Schools', value: '7' },
              { label: 'SSA Required', value: '2', tone: 'alert' },
              { label: 'Without SSA', value: '2 schools', tone: 'caution' },
              { label: 'Ready for Planning', value: '5', tone: 'good' },
              { label: 'Next Action', value: 'Schedule training' },
            ],
          },
        },
      ],
    }, '/clusters');
    expect(html).toMatch(/<dd class="[^"]*text-\[var\(--edify-accent-text\)\][^"]*">7</);
    expect(html).toMatch(/<dd class="[^"]*text-\[var\(--edify-danger\)\][^"]*">2</);
    expect(html).toMatch(/<dd class="[^"]*text-\[var\(--edify-warning\)\][^"]*">2 schools</);
    expect(html).toMatch(/<dd class="[^"]*text-\[var\(--edify-success\)\][^"]*">5</);
    expect(html).toMatch(/<dd class="[^"]*text-\[var\(--edify-accent-text\)\][^"]*">Schedule training</);
  });
});
