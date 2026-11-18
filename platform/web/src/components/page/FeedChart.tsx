/*
 * A bar chart (components/data_chart.html) from the data the page charts:
 * one bar per category against an axis with round ticks, two series drawn as
 * a cut-out bar (barParts), a legend for two series, the axis title under
 * it, and the figures as a table under "View chart data", as there.
 */
import type { PageChart } from '@/gen/edify/screens/v1/page_pb';
import { barParts, chartAxis, chartValue } from '@/lib/schoolProfile';

/** The existing chart's two series colours: the brand blue, then its light tint. */
const SERIES = ['bg-[var(--brand-primary)] text-white', 'bg-[color-mix(in_srgb,var(--brand-primary)_32%,var(--edify-surface))] text-[var(--edify-text)]'] as const;

function seriesClass(index: number): string {
  return SERIES[index % SERIES.length] ?? SERIES[0];
}

function pct(share: number): string {
  return `${(share * 100).toFixed(3)}%`;
}

export function FeedChart({ chart }: { chart: PageChart }) {
  const axis = chartAxis(chart);
  const twoSeries = chart.series.length === 2;
  return (
    <section aria-label={chart.title || 'Chart'} data-block="chart" className="card p-4 shadow-[var(--edify-shadow-sm)]">
      {chart.title ? <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{chart.title}</h2> : null}
      {chart.subtitle ? <p className="text-[length:var(--edify-text-label-size)] font-medium text-[var(--edify-text-muted)]">{chart.subtitle}</p> : null}
      {twoSeries ? (
        <ul className="ml-auto mt-3 flex w-fit flex-wrap gap-4 rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 py-1.5 text-[13px] font-medium" aria-label="Legend">
          {chart.series.map((series, index) => (
            <li key={series.name} className="flex items-center gap-1.5">
              <span aria-hidden="true" className={`h-3 w-3 ${seriesClass(index)}`} />
              {series.name}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-3 overflow-x-auto" aria-hidden="true">
        <div className="min-w-[30rem] pr-5">
          {chart.categories.map((category, row) => {
            const parts = barParts(chart.series.map((series) => series.values[row] ?? Number.NaN), axis.min, axis.max);
            return (
              <div key={category} className="grid grid-cols-[minmax(6rem,14rem)_1fr] items-center gap-3 py-1">
                <span className="text-right text-[13px] font-medium">{category}</span>
                <span className="relative block h-6">
                  {parts.map((part) => (
                    <span
                      key={part.series}
                      className={`absolute inset-y-0 flex items-center justify-end ${seriesClass(part.series)}`}
                      style={{ left: pct(part.from), width: pct(part.to - part.from) }}
                    >
                      {part.inside ? <span className="px-1.5 text-[13px] font-bold">{chartValue(part.value)}</span> : null}
                    </span>
                  ))}
                  {parts
                    .filter((part) => !part.inside)
                    .map((part) => (
                      <span key={`v${part.series}`} className="absolute inset-y-0 flex items-center pl-2 text-[13px] font-medium" style={{ left: pct(part.to) }}>
                        {chartValue(part.value)}
                      </span>
                    ))}
                </span>
              </div>
            );
          })}
          <div className="grid grid-cols-[minmax(6rem,14rem)_1fr] gap-3">
            <span />
            <span className="relative block h-5 border-t border-[var(--edify-text-muted)] text-[12px] font-medium">
              {axis.ticks.map((tick) => (
                <span key={tick} className="absolute top-1 -translate-x-1/2" style={{ left: pct((tick - axis.min) / (axis.max - axis.min)) }}>
                  {chartValue(tick)}
                </span>
              ))}
            </span>
          </div>
          {chart.axisTitle ? <p className="mt-1 text-center text-[12px] font-medium italic">{chart.axisTitle}</p> : null}
        </div>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-[13px] font-semibold">View chart data</summary>
        <table className="mt-2 w-full text-[13px]">
          <thead>
            <tr className="border-b border-[var(--edify-table-divider)] text-left">
              <th className="py-1 pr-3 font-semibold">Category</th>
              {chart.series.map((series) => (
                <th key={series.name} className="py-1 pr-3 text-right font-semibold">{series.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {chart.categories.map((category, row) => (
              <tr key={category} className="border-b border-[var(--edify-table-divider)]">
                <td className="py-1 pr-3">{category}</td>
                {chart.series.map((series) => (
                  <td key={series.name} className="py-1 pr-3 text-right">{series.values[row] === undefined ? '—' : chartValue(series.values[row])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
