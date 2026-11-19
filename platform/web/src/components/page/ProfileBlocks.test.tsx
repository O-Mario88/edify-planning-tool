/**
 * The block kinds the school profile answers with (facts, the insights rail,
 * charts, Participation's Planned/Completed switch) and the profile's header,
 * drawn from answers shaped as the Go gateway gave them for School 1000 on
 * the development database (2026-11-13), trimmed.
 */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { GetSchoolProfileResponseSchema } from '@/gen/edify/screens/v1/school_profile_pb';

import { PageHeader } from '../blocks/PageHeader';
import { FeedBlocks } from './FeedBlocks';

const DRAWER = 'http://localhost:8182/schools/1000';

function answer(json: JsonValue) {
  return fromJson(GetSchoolProfileResponseSchema, json);
}

function draw(json: JsonValue, selectable = false): string {
  return renderToStaticMarkup(<FeedBlocks blocks={answer(json).blocks} pagePath="/schools/1000" drawerHref={DRAWER} selectable={selectable} />);
}

describe('the profile’s blocks', () => {
  it('draws the facts with a district linked to its page', () => {
    const html = draw({ blocks: [{ facts: { facts: [{ label: 'School ID', value: '1000' }, { label: 'District', value: 'Mukono', href: '/districts/cmw9p546g00kclteihg5e' }] } }] });
    expect(html).toContain('data-block="facts"');
    expect(html).toContain('>School ID</dt>');
    expect(html).toContain('href="/districts/cmw9p546g00kclteihg5e"');
  });

  it('draws the insights rail: figure, meters out of their scale and attention links', () => {
    const html = draw({
      blocks: [
        {
          rail: {
            title: 'Profile Insights',
            subtitle: 'FY 2026/27',
            parts: [
              { key: 'ssa', title: 'SSA Performance', figure: '6.25', figureHref: '/schools/x?tab=ssa&fy=2027', figureNote: 'baseline 5.90', meters: [{ label: 'Leadership', value: '6.9', fraction: 0.69, href: '/schools/x?fy=2027&what=intervention&key=leadership' }], note: 'Each intervention out of 10; a line opens its schools.' },
              { key: 'attention', title: 'Needs Attention', links: [{ text: '1 visit is past its date and not done', href: '/schools/x?fy=2027&what=visits_overdue' }] },
            ],
          },
        },
      ],
    });
    expect(html).toContain('aria-label="Profile Insights"');
    expect(html).toContain('href="/schools/x?tab=ssa&amp;fy=2027"');
    expect(html).toContain('width:69%');
    expect(html).toContain('>6.9<');
    expect(html).toContain('href="/schools/x?fy=2027&amp;what=visits_overdue"');
    expect(html).toContain('1 visit is past its date and not done');
  });

  it('draws a chart card as the existing web does, for its chart system to fill', () => {
    const html = draw({
      blocks: [{ chart: { title: 'SSA score by intervention', subtitle: 'FY 2025/26 and FY 2026/27', horizontal: true, categories: ['Christlike Behaviour'], series: [{ name: 'FY 2025/26', values: [6.6] }, { name: 'FY 2026/27', values: [6.4] }], max: 10, axisTitle: 'SSA score (0–10)' } }],
    });
    // components/bar_chart.html: the card, its header (no title band) and the
    // plot EdifyChartSystem draws into once the page runs (lib/legacyChart).
    expect(html).toContain('<section class="card edify-data-chart" aria-label="SSA score by intervention" data-block="chart">');
    expect(html).toContain('<header class="edify-data-chart__header" data-no-titlebar=""><h3 class="edify-data-chart__title">SSA score by intervention</h3>');
    expect(html).toContain('<p class="edify-data-chart__subtitle">FY 2025/26 and FY 2026/27</p>');
    expect(html).toContain('<div class="edify-data-chart__plot"></div>');
  });

  it('draws Participation’s switch with the open part shown and the other kept hidden', () => {
    const html = draw(
      {
        blocks: [
          {
            segments: {
              title: 'Planned & Completed Activities',
              subtitle: '1 planned · 2 completed · 1 overdue',
              caption: 'Visits and trainings at this school.',
              segments: [
                { label: 'Planned', active: true, count: '1', blocks: [{ table: { columns: [{ label: 'Activity' }], rows: [{ cells: [{ text: 'Donor Visit' }], pickId: 'a1', pickLabel: 'Select Donor Visit' }] } }] },
                { label: 'Completed', count: '2', blocks: [{ table: { columns: [{ label: 'Activity' }], rows: [{ cells: [{ text: 'Leadership coaching' }] }] } }] },
              ],
            },
          },
        ],
      },
      true,
    );
    expect(html).toMatch(/data-edify-tab="" aria-pressed="true">Planned <span data-edify-tab-count="" data-segment-count="">1<\/span>/);
    expect(html).toContain('data-pick="a1"');
    expect(html).toMatch(/role="tabpanel" hidden=""[^>]*>.*Leadership coaching/);
    expect(html).not.toContain('not-drawn');
  });
});

describe('the profile’s header', () => {
  const header = answer({
    header: {
      backLabel: 'Back to School Directory',
      backHref: '/schools',
      title: 'Central Division Primary School',
      description: 'School ID: 1000',
      badges: [
        { text: 'SSA FY2027: 6.25', tone: 'good', title: 'Source: Keyed by Impact Assessment · Confirmed' },
        { text: 'Staff visit scheduled', tone: 'plain', title: 'A staff support visit is scheduled', icon: 'lock' },
      ],
      actions: [
        { key: 'edit_details', label: 'Edit Details', primary: true, enabled: true, href: '/schools/x/edit-drawer', drawer: true },
        { key: 'enter_ssa_score', label: 'Enter SSA Score', reason: 'SSA already entered for FY2027' },
      ],
    },
  }).header!;
  const html = renderToStaticMarkup(<PageHeader header={header} hrefOf={() => DRAWER} />);

  it('draws the back link, the badges and the doors, a drawer opening on the existing web', () => {
    expect(html).toContain('href="/schools"');
    expect(html).toContain('Back to School Directory');
    expect(html).toContain('title="Source: Keyed by Impact Assessment · Confirmed"');
    expect(html).toContain(`href="${DRAWER}"`);
    expect(html).toMatch(/disabled="" title="SSA already entered for FY2027"/);
  });

  it('draws the visit lock before its badge’s words and the pencil on Edit Details, as the existing page does', () => {
    expect(html).toMatch(/<svg viewBox="0 0 16 16"[^>]*><path d="M4\.5 7V5[^"]*"><\/path><\/svg>Staff visit scheduled/);
    expect(html).toMatch(/<path[^>]*d="M11 5h-6a2 2 0 00-2 2v12[^"]*"><\/path><\/svg><span>Edit Details<\/span>/);
    expect(html.match(/<svg/g)).toHaveLength(3);
  });

  it('never links back outside the site', () => {
    const outside = { ...header, backHref: '//evil.example' };
    expect(renderToStaticMarkup(<PageHeader header={outside} hrefOf={() => DRAWER} />)).not.toContain('evil.example');
  });
});
