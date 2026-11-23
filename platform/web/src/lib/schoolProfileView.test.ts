import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import {
  PageActionSchema,
  PageBlockSchema,
  PageCellSchema,
  PageChartSchema,
  PageColumnSchema,
  PageFactSchema,
  PageFactsSchema,
  PageHeaderSchema,
  PageLinkSchema,
  PageLinksSchema,
  PageMeterSchema,
  PageMetricSchema,
  PagePanelItemSchema,
  PagePanelSchema,
  PageRailPartSchema,
  PageRailSchema,
  PageRowSchema,
  PageSeriesSchema,
  PageStripSchema,
  PageTableSchema,
} from '@/gen/edify/screens/v1/page_pb';
import type { PageBlock } from '@/gen/edify/screens/v1/page_pb';

import { championChecks, coreFigures, coreSchoolView, honestSsa, interventionRows, readinessWord, leadMetrics, metricLine, panelLine, schoolIdentity, splitHeroActions, stripNamed, trendPoints } from './schoolProfileView';

const action = (label: string) => create(PageActionSchema, { key: label, label, enabled: true, href: '/x' });
const metric = (label: string, value = '1', helper = '', note = '') => create(PageMetricSchema, { label, value, helper, note });
const strip = (title: string, labels: readonly string[]): PageBlock =>
  create(PageBlockSchema, { kind: { case: 'strip', value: create(PageStripSchema, { title, metrics: labels.map((label) => metric(label)) }) } });
const panel = (title: string, texts: readonly string[]): PageBlock =>
  create(PageBlockSchema, {
    kind: {
      case: 'panel',
      value: create(PagePanelSchema, { title, items: texts.map((text) => create(PagePanelItemSchema, { kind: { case: 'text', value: text } })) }),
    },
  });
const facts = (pairs: Readonly<Record<string, string>>): PageBlock =>
  create(PageBlockSchema, {
    kind: {
      case: 'facts',
      value: create(PageFactsSchema, { facts: Object.entries(pairs).map(([label, value]) => create(PageFactSchema, { label, value })) }),
    },
  });
const chart = (title: string, categories: string[], values: number[]): PageBlock =>
  create(PageBlockSchema, {
    kind: {
      case: 'chart',
      value: create(PageChartSchema, { title, categories, series: [create(PageSeriesSchema, { name: 'Average SSA score', values })], max: 10 }),
    },
  });

describe('splitHeroActions', () => {
  it('keeps the six header buttons in the design order and moves the rest to the Actions menu', () => {
    const { row, menu } = splitHeroActions(['Close School', 'Reassign Owner', 'Edit Details', 'Enter SSA Score', 'Schedule'].map(action));
    expect(row.map((item) => item.label)).toEqual(['Edit Details', 'Schedule', 'Enter SSA Score', 'Close School']);
    expect(menu.map((item) => item.label)).toEqual(['Reassign Owner']);
  });
});

describe('schoolIdentity', () => {
  const blocks = [facts({ 'School ID': '1546', Type: 'Core', District: 'Mukono', 'Sub-region': 'Central', 'Sub-county': 'Central Division', Cluster: 'Cluster A', CCEO: 'Paul N.', 'Programme Lead': 'Lead 1', Status: 'Operating', 'Fiscal Year': 'FY 2026/27' })];

  it('reads the school from the answer, naming the school type', () => {
    const identity = schoolIdentity(create(PageHeaderSchema, { title: 'A School', description: 'School ID: 1546' }), blocks);
    expect(identity.schoolId).toBe('1546');
    expect(identity.typeLabel).toBe('Core School');
    expect(identity.status).toBe('Operating');
    expect(identity.place.map((fact) => fact.value)).toEqual(['Mukono', 'Central', 'Central Division']);
    expect(identity.people.map((fact) => fact.label)).toEqual(['CCEO', 'Programme Lead', 'Fiscal Year']);
    expect(identity.cluster?.value).toBe('Cluster A');
  });

  it('leaves out a fact the answer does not carry', () => {
    const identity = schoolIdentity(create(PageHeaderSchema, { description: 'School ID: 9' }), [facts({ District: 'Gulu' })]);
    expect(identity.schoolId).toBe('9');
    expect(identity.typeLabel).toBe('');
    expect(identity.place.map((fact) => fact.label)).toEqual(['District']);
    expect(identity.cluster).toBeUndefined();
  });
});

describe('metrics', () => {
  it('splits the lead tiles from the rest, in the lead order', () => {
    const found = stripNamed([strip('Operations', ['Nothing Planned', 'Visits Completed', 'Online Trainings'])], 'Operations');
    const { lead, more } = leadMetrics(found, ['Visits Completed', 'Online Trainings']);
    expect(lead.map((item) => item.label)).toEqual(['Visits Completed', 'Online Trainings']);
    expect(more.map((item) => item.label)).toEqual(['Nothing Planned']);
  });

  it('has no tiles for a strip the reader was not given', () => {
    expect(stripNamed([], 'Loans And Business Transformation')).toBeUndefined();
    expect(leadMetrics(undefined, ['Disbursed'])).toEqual({ lead: [], more: [] });
  });

  it('writes the short line, else the fuller note', () => {
    expect(metricLine(metric('A', '1', 'of 4', 'long'))).toBe('of 4');
    expect(metricLine(metric('A', '1', '', 'previous 3.50 · +1.00'))).toBe('previous 3.50 · +1.00');
  });
});

describe('trendPoints', () => {
  it('reads the yearly confirmed averages and drops the school count from the axis', () => {
    const points = trendPoints([chart('Annual SSA Progress', ['FY 2025/26 (1 school)', 'FY 2026/27 (12 schools)'], [3.5, 4.5])]);
    expect(points).toEqual([{ label: 'FY 2025/26', value: 3.5 }, { label: 'FY 2026/27', value: 4.5 }]);
  });

  it('never draws a year without a reading as a zero', () => {
    expect(trendPoints([chart('Annual SSA Progress', ['FY 2025/26', 'FY 2026/27'], [Number.NaN, 4.5])])).toEqual([{ label: 'FY 2026/27', value: 4.5 }]);
    expect(trendPoints([])).toEqual([]);
  });
});

describe('honestSsa', () => {
  const performance = (assessed: string, ssaValue: string, ssaNote: string): PageBlock =>
    create(PageBlockSchema, {
      kind: {
        case: 'strip',
        value: create(PageStripSchema, {
          title: 'Performance And Impact',
          metrics: [metric('SSA Score', ssaValue, '', ssaNote), metric('Schools Assessed', assessed, 'of 1 in FY 2026/27')],
        }),
      },
    });
  const rail = (figure: string, figureNote: string): PageBlock =>
    create(PageBlockSchema, {
      kind: {
        case: 'rail',
        value: create(PageRailSchema, {
          title: 'Profile Insights',
          parts: [create(PageRailPartSchema, { key: 'ssa', figure, figureNote, meters: [create(PageMeterSchema, { label: 'Leadership', value: '0.0', fraction: 0 })] })],
        }),
      },
    });
  const standing = (intervention: string, previous: string, current: string, change: string, trend: string): PageBlock =>
    create(PageBlockSchema, {
      kind: {
        case: 'table',
        value: create(PageTableSchema, {
          title: 'Best Performing And Struggling Intervention',
          columns: ['Standing', 'Intervention', 'Previous', 'Current', 'Change', 'Trend'].map((label) => create(PageColumnSchema, { label })),
          rows: [create(PageRowSchema, { cells: ['Best performing', intervention, previous, current, change, trend].map((text) => create(PageCellSchema, { text })) })],
        }),
      },
    });
  const ssaMetric = (blocks: readonly PageBlock[]) => stripNamed(blocks, 'Performance And Impact')?.metrics[0];
  const railPart = (blocks: readonly PageBlock[]) => {
    const block = blocks.find((item) => item.kind.case === 'rail');
    return block?.kind.case === 'rail' ? block.kind.value.parts[0] : undefined;
  };
  const cells = (blocks: readonly PageBlock[]) => {
    const block = blocks.find((item) => item.kind.case === 'table');
    return block?.kind.case === 'table' ? block.kind.value.rows[0]?.cells.map((cell) => cell.text) : [];
  };

  it('never shows 0.00 for a school with no confirmed SSA this year', () => {
    const out = honestSsa([performance('0', '0.00', 'previous 5.90'), rail('0.00', 'baseline 5.90 · 0.00 since FY 2025/26')]);
    expect(ssaMetric(out)?.value).toBe('Not Assessed');
    expect(ssaMetric(out)?.note).toBe('previous 5.90');
    expect(railPart(out)?.figure).toBe('Not Assessed');
    expect(railPart(out)?.figureNote).toBe('Last confirmed 5.90 · Not Compared');
    expect(railPart(out)?.meters[0]?.value).toBe('—');
  });

  it('says Not Compared where there is no earlier SSA, and keeps the real score', () => {
    const out = honestSsa([performance('1', '4.50', 'previous 0'), rail('4.50', 'baseline 0.00 · +4.50 since FY 2025/26')]);
    expect(ssaMetric(out)?.value).toBe('4.50');
    expect(ssaMetric(out)?.note).toBe('Not Compared');
    expect(railPart(out)?.figure).toBe('4.50');
    expect(railPart(out)?.figureNote).toBe('Not Compared: no earlier SSA');
  });

  it('blanks the placeholder zeros of an intervention row with no score', () => {
    const out = honestSsa([performance('0', '0.00', 'previous 0'), standing('No intervention has a confirmed score in FY 2026/27 yet', '0', '0', '0', '—')]);
    expect(cells(out)).toEqual(['Best performing', 'No intervention has a confirmed score in FY 2026/27 yet', '—', '—', '—', 'Not Compared']);
  });

  it('leaves a real comparison exactly as Go sent it', () => {
    const blocks = [performance('1', '4.50', 'previous 3.50 · +1.00'), rail('4.50', 'baseline 3.50 · +1.00 since FY 2025/26'), standing('Leadership', '2.20', '7.10', '+4.90', 'Improved')];
    const out = honestSsa(blocks);
    expect(ssaMetric(out)?.note).toBe('previous 3.50 · +1.00');
    expect(railPart(out)?.figureNote).toBe('baseline 3.50 · +1.00 since FY 2025/26');
    expect(cells(out)).toEqual(['Best performing', 'Leadership', '2.20', '7.10', '+4.90', 'Improved']);
  });

  it('does not change the answer it was given', () => {
    const blocks = [performance('0', '0.00', 'previous 5.90')];
    honestSsa(blocks);
    expect(ssaMetric(blocks)?.value).toBe('0.00');
  });
});

describe('panelLine', () => {
  it('splits a labelled sentence into its label and value', () => {
    expect(panelLine('Cluster sessions: 0 attended of 0 invited')).toEqual({ label: 'Cluster sessions', value: '0 attended of 0 invited' });
  });

  it('leaves a plain sentence whole', () => {
    expect(panelLine('No Core plan for FY 2026/27.')).toEqual({ label: '', value: 'No Core plan for FY 2026/27.' });
  });
});

describe('coreSchoolView', () => {
  it('finds each card by the title Go gave it, and the Champion readiness in its title', () => {
    const view = coreSchoolView([
      strip('Performance overview', ['SSA Trajectory', 'Package', 'Champion Readiness']),
      panel('Package and Support', ['No Core plan for FY 2026/27.']),
      panel('Participation', ['Cluster sessions: 0 attended of 0 invited']),
      panel('Outcomes', ['Enrolment: — → —']),
      panel('Recommended Support', ['No open recommendation.']),
      panel('Champion Readiness: Insufficient Evidence', ['Not judged']),
    ]);
    expect(view.readiness).toBe('Insufficient Evidence');
    expect(view.metrics.map((item) => item.label)).toEqual(['SSA Trajectory', 'Package', 'Champion Readiness']);
    expect(view.package?.title).toBe('Package and Support');
    expect(view.participation?.title).toBe('Participation');
    expect(view.outcomes?.title).toBe('Outcomes');
    expect(view.support?.title).toBe('Recommended Support');
    expect(view.champion?.title).toBe('Champion Readiness: Insufficient Evidence');
    expect(view.others).toEqual([]);
  });

  it('keeps a card it has no place for, so nothing Go sends is dropped', () => {
    const view = coreSchoolView([panel('Something New', ['A line'])]);
    expect(view.others.map((block) => (block.kind.case === 'panel' ? block.kind.value.title : ''))).toEqual(['Something New']);
    expect(view.readiness).toBe('');
  });
});

describe('the Core School tab as the design draws it', () => {
  const metric = (label: string, value: string, helper = '') => create(PageMetricSchema, { label, value, helper });
  const coreStrip = (packageValue: string, packageHelper: string) =>
    create(PageBlockSchema, {
      kind: {
        case: 'strip',
        value: create(PageStripSchema, {
          title: 'Performance overview',
          metrics: [metric('SSA Trajectory', 'Improved'), metric('Package', packageValue, packageHelper), metric('Champion Readiness', 'Not Yet Ready', "Edify's Champion rule")],
        }),
      },
    });
  const handovers = 'Partner hand-overs: 2 not yet scheduled · 1 scheduled · 3 completed';
  const matrix = (rows: readonly (readonly string[])[]) =>
    create(PageBlockSchema, {
      kind: {
        case: 'table',
        value: create(PageTableSchema, {
          title: 'Intervention Matrix',
          columns: ['Intervention', 'Previous (FY 2025/26)', 'Current (FY 2026/27)', 'Change', 'Status', 'Target', 'To Target'].map((label) => create(PageColumnSchema, { label })),
          rows: rows.map((cells) => create(PageRowSchema, { cells: cells.map((text) => create(PageCellSchema, { text })) })),
        }),
      },
    });
  const links = (title: string, words: readonly string[]) =>
    create(PagePanelSchema, {
      title,
      items: [create(PagePanelItemSchema, { kind: { case: 'links', value: create(PageLinksSchema, { links: words.map((text) => create(PageLinkSchema, { text })) }) } })],
    });

  it('reads the intervention rows, leaving out the all-interventions total', () => {
    const rows = interventionRows([matrix([['Leadership', '2.20', '7.10', '+4.90', 'Improved', '10.0', '2.90'], ['All interventions', '3.0', '4.5', '+1.5', 'Improved', '10.0', '5.5']])]);
    expect(rows.map((row) => row.name)).toEqual(['Leadership']);
    expect(rows[0]).toMatchObject({ previous: '2.20', current: '7.10', change: '+4.90', status: 'Improved' });
  });

  it('gives the five figures from what Go answered', () => {
    const view = coreSchoolView([coreStrip('25%', 'Visits 1/4 · Trainings 1/4'), panel('Package and Support', [handovers])]);
    const rows = interventionRows([matrix([['Leadership', '2.20', '7.10', '+4.90', 'Improved', '10.0', '2.90'], ['Financial Health', '—', '—', '—', 'Not Compared', '10.0', '—']])]);
    const figures = coreFigures(view, 'FY 2026/27', rows);
    expect(figures.map((item) => item.label)).toEqual(['Programme Package', 'Interventions', 'Champion Readiness', 'Partner Hand-overs', 'Implementation Progress']);
    expect(figures.map((item) => item.value)).toEqual(['4 visits · 4 trainings', '1', 'Not Yet Ready', '1 Scheduled', '25%']);
    expect(figures[3]?.helper).toBe('3 Completed');
    expect(figures[4]?.helper).toBe('Visits 1/4 · Trainings 1/4');
  });

  it('shows no progress figure for a school with no Core plan', () => {
    const view = coreSchoolView([coreStrip('No package', 'No Core plan this year'), panel('Package and Support', ['No Core plan for FY 2026/27.', handovers])]);
    const figures = coreFigures(view, 'FY 2026/27', []);
    expect(figures[0]?.value).toBe('No Package');
    expect(figures[0]?.helper).toBe('for FY 2026/27');
    expect(figures[1]?.value).toBe('0');
    expect(figures[4]?.value).toBe('—');
  });

  it('reads the Champion rule checks in their own words', () => {
    const checks = championChecks(links('Champion Readiness: Not Yet Ready', ['Met: Latest SSA', 'Not met: No intervention below 7.0', 'Not judged: All package work']));
    expect(checks.map((check) => check.state)).toEqual(['met', 'not', 'none']);
    expect(checks[1]?.text).toBe('No intervention below 7.0');
  });

  it('takes the readiness from the header badge, without its label', () => {
    expect(readinessWord(['SSA FY2027: 4.5', 'Readiness: Ready for Support Planning'])).toBe('Ready for Support Planning');
    expect(readinessWord(['SSA FY2027: 4.5'])).toBe('');
  });

  it('finds the recommendation records that follow the section heading', () => {
    const records = panel('', ['Leadership (4.0, Low)']);
    const view = coreSchoolView([create(PageBlockSchema, { kind: { case: 'section', value: 'Recommended Support' } }), records]);
    expect(view.support).toBe(records.kind.value);
    expect(view.others).toEqual([]);
  });

  it('keeps the two page links apart from the cards', () => {
    const view = coreSchoolView([panel('', ['A line'])]);
    expect(view.others).toHaveLength(1);
  });
});
