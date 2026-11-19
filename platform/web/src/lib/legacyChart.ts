/**
 * Charts drawn by the existing web's own chart system: the pinned ApexCharts,
 * static/js/chart-standard.js and the EdifyChartSystem script, copied into
 * public/static by scripts/sync-tokens.mjs. A chart block is turned back into
 * the payload the existing page hands that system (chart_tags.py), so every
 * chart here has the existing geometry: the 220px plot, bars no thicker than
 * 22px, the cut-out horizontal bars, the series palette and the data table.
 */
import type { PageChart } from '@/gen/edify/screens/v1/page_pb';
import CHART_SCRIPTS from '@/styles/generated/legacy-chart-scripts.json';

export interface ChartPayload {
  readonly chart: { readonly type: 'bar' };
  readonly plotOptions?: { readonly bar: { readonly horizontal: boolean } };
  readonly series: ReadonlyArray<{ readonly name: string; readonly data: readonly number[] }>;
  readonly xaxis: { readonly categories: readonly string[] };
  readonly yaxis?: { readonly min?: number; readonly max?: number; readonly title?: { readonly text: string } };
}

/** The payload the existing page drew this chart from. */
export function chartPayload(chart: PageChart): ChartPayload {
  const scale = chart.max > 0 ? { min: chart.min, max: chart.max } : {};
  const unit = chart.axisTitle ? { title: { text: chart.axisTitle } } : {};
  const yaxis = { ...scale, ...unit };
  return {
    chart: { type: 'bar' },
    ...(chart.horizontal ? { plotOptions: { bar: { horizontal: true } } } : {}),
    series: chart.series.map((series) => ({ name: series.name, data: [...series.values] })),
    xaxis: { categories: [...chart.categories] },
    ...(Object.keys(yaxis).length ? { yaxis } : {}),
  };
}

/** What the chart scripts put on window. */
export interface ChartSystem {
  formBase(payload: ChartPayload): unknown;
  renderDetached(el: HTMLElement, options: unknown): { destroy?: () => void } | null;
}

let loading: Promise<ChartSystem> | null = null;

function loadScript(src: string): Promise<void> {
  const present = document.querySelector<HTMLScriptElement>(`script[src="${src}"]`);
  if (present?.dataset.loaded === 'true') return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = present ?? document.createElement('script');
    script.addEventListener(
      'load',
      () => {
        script.dataset.loaded = 'true';
        resolve();
      },
      { once: true },
    );
    script.addEventListener('error', () => reject(new Error(`Could not load ${src}`)), { once: true });
    if (!present) {
      script.src = src;
      script.async = false;
      document.head.appendChild(script);
    }
  });
}

/** The chart system, once its scripts have run in the existing web's order. */
export function loadChartSystem(): Promise<ChartSystem> {
  loading ??= (async () => {
    for (const src of CHART_SCRIPTS) await loadScript(src);
    const system = (window as unknown as { EdifyChartSystem?: ChartSystem }).EdifyChartSystem;
    if (!system) throw new Error('The chart system did not start.');
    return system;
  })().catch((error: unknown) => {
    loading = null;
    throw error;
  });
  return loading;
}
