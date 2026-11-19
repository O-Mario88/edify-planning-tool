/*
 * A bar chart in the platform's cut-out form, as the app draws it
 * (PageChartView.tsx, after static/js/chart-standard.js): each category's
 * name over one track; every series from zero on one scale, the longest
 * drawn first so each shorter bar lies on top; the shortest value inside its
 * bar when it fits, else the figures after the longest bar. Each series
 * keeps its shade of the first series' hue; a ruled legend names them; the
 * axis is one rule with its unit under it. "View chart data" opens the same
 * figures as a list. Widths are shares of the track, so it needs no measure.
 */
import { ChevronRight } from 'lucide-react';
import type { CSSProperties } from 'react';

import type { PageChart } from '@/gen/edify/screens/v1/page_pb';

/** The share of the first series' hue in each series' shade (chart-standard.js SHADES). */
const SHADES = [100, 33, 78, 10, 55, 89, 44, 22];
/** A bar shorter than this share of the track writes its number after the bars. */
const INSIDE_MIN_SHARE = 0.14;

/** A round scale end at or above the largest value, as the web picks it. */
export function scaleOf(chart: Pick<PageChart, 'series' | 'max'>): { max: number; step: number } {
  const top = Math.max(0, ...chart.series.flatMap((series) => series.values));
  if (chart.max > 0 && chart.max >= top) return { max: chart.max, step: chart.max / (chart.max % 5 === 0 ? 5 : 4) };
  if (!top) return { max: 1, step: 1 };
  const rough = top / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((m) => m >= rough) ?? rough;
  return { max: Math.ceil(top / step) * step, step };
}

const mark = (value: number) => String(Number(value.toFixed(1)));
const shadeOf = (index: number) => SHADES[index % SHADES.length] ?? 100;
const fill = (index: number): CSSProperties => ({ '--ph-shade': `${shadeOf(index)}%` }) as CSSProperties;
const at = (share: number): CSSProperties => ({ '--ph-share': String(Math.min(1, Math.max(0, share))) }) as CSSProperties;

export function PhoneChart({ chart }: { chart: PageChart }) {
  const scale = scaleOf(chart);
  const isEmpty = chart.series.every((series) => series.values.every((value) => value === 0));
  const share = (value: number) => Math.min(1, value / scale.max);
  const ticks: number[] = [];
  for (let tick = 0; tick <= scale.max + scale.step / 1000; tick += scale.step) ticks.push(Number(tick.toFixed(6)));
  return (
    <section data-ph="card" data-padded="" aria-label={chart.title}>
      <div data-ph="chart">
        <div>
          <h2 data-ph="table-title">{chart.title}</h2>
          {chart.subtitle ? <p data-ph="panel-subtitle">{chart.subtitle}</p> : null}
        </div>
        {chart.series.length > 1 && !isEmpty ? (
          <div data-ph="chart-legend">
            {chart.series.map((series, index) => (
              <span key={series.name} data-ph="chart-key">
                <span data-ph="chart-swatch" style={fill(index)} aria-hidden="true" />
                {series.name}
              </span>
            ))}
          </div>
        ) : null}
        {isEmpty ? (
          <p data-ph="panel-text">Nothing recorded for this period yet.</p>
        ) : (
          <div data-ph="chart-rows">
            {chart.categories.map((category, row) => {
              const bars = chart.series
                .map((series, index) => ({ index, value: series.values[row] ?? 0 }))
                .sort((a, b) => b.value - a.value || b.index - a.index);
              const longest = bars[0];
              const shortest = bars.length > 1 ? bars[bars.length - 1] : undefined;
              const fitsInside = shortest !== undefined && share(shortest.value) >= INSIDE_MIN_SHARE;
              const isEmptyRow = bars.every((bar) => bar.value === 0);
              const after =
                shortest && !fitsInside && !isEmptyRow
                  ? bars.map((bar) => `${mark(bar.value)} ${chart.series[bar.index]?.name ?? ''}`).join(', ')
                  : longest
                    ? mark(longest.value)
                    : '';
              const label = `${category}: ${bars.map((bar) => `${mark(bar.value)} ${chart.series[bar.index]?.name ?? ''}`).join(', ')}`;
              return (
                <div key={category} role="img" aria-label={label}>
                  <span data-ph="chart-name" aria-hidden="true">
                    {category}
                  </span>
                  <span data-ph="chart-track" aria-hidden="true">
                    {chart.series.length === 1 ? <span data-ph="chart-whole" /> : null}
                    {bars.map((bar) => (
                      <span key={bar.index} data-ph="chart-bar" data-light={shadeOf(bar.index) < 60 || undefined} style={{ ...fill(bar.index), ...at(share(bar.value)) }}>
                        {fitsInside && shortest?.index === bar.index ? mark(bar.value) : null}
                      </span>
                    ))}
                    <span data-ph="chart-end" style={at(longest ? share(longest.value) : 0)}>
                      {after}
                    </span>
                  </span>
                </div>
              );
            })}
            <span data-ph="chart-axis" aria-hidden="true">
              {ticks.map((tick) => (
                <span key={tick} data-ph="chart-tick" style={at(share(tick))}>
                  {mark(tick)}
                </span>
              ))}
            </span>
            {chart.axisTitle ? <span data-ph="chart-unit">{chart.axisTitle}</span> : null}
          </div>
        )}
        <details data-ph="chart-data">
          <summary data-ph="chart-toggle">
            <ChevronRight size={14} aria-hidden="true" />
            View chart data
          </summary>
          <div data-ph="chart-list">
            {chart.categories.map((category, row) => (
              <div key={category} data-ph="chart-list-row">
                <span data-ph="list-title">{category}</span>
                <span data-ph="list-line">{chart.series.map((series) => `${series.name}: ${mark(series.values[row] ?? 0)}`).join(' · ')}</span>
              </div>
            ))}
          </div>
        </details>
      </div>
    </section>
  );
}
