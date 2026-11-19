/**
 * A chart block becomes the payload the existing web hands its chart system
 * (apps/frontend/templatetags/chart_tags.py): a bar chart, horizontal when
 * the page drew it so, its series and categories, and the y axis only when
 * the page set a scale or a unit.
 */
import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { PageChartSchema } from '@/gen/edify/screens/v1/page_pb';

import { chartPayload } from './legacyChart';

describe('the payload a chart is drawn from', () => {
  it('rebuilds a score chart as chart_tags.score_chart builds it', () => {
    const chart = create(PageChartSchema, {
      title: 'SSA score by intervention',
      horizontal: true,
      categories: ['Leadership', 'Enrolment'],
      series: [{ name: 'SSA score', values: [6.5, 4] }],
      min: 0,
      max: 10,
      axisTitle: 'SSA score (0–10)',
    });
    expect(chartPayload(chart)).toEqual({
      chart: { type: 'bar' },
      plotOptions: { bar: { horizontal: true } },
      series: [{ name: 'SSA score', data: [6.5, 4] }],
      xaxis: { categories: ['Leadership', 'Enrolment'] },
      yaxis: { min: 0, max: 10, title: { text: 'SSA score (0–10)' } },
    });
  });

  it('leaves out what the page did not set: a column chart with no scale', () => {
    const chart = create(PageChartSchema, { categories: ['Q1', 'Q2'], series: [{ name: 'Count', values: [3, 0] }] });
    expect(chartPayload(chart)).toEqual({
      chart: { type: 'bar' },
      series: [{ name: 'Count', data: [3, 0] }],
      xaxis: { categories: ['Q1', 'Q2'] },
    });
  });
});
