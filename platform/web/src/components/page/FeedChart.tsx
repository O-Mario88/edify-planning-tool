'use client';

/*
 * A chart card as the existing web draws it (templates/components/
 * bar_chart.html): the card's title and the line under it, then the plot,
 * drawn by the existing web's own chart system (EdifyChartSystem over
 * static/js/chart-standard.js and the pinned ApexCharts, lib/legacyChart)
 * from the payload the existing page hands it. The geometry, palette, cut-out
 * bars, paging and "View chart data" table are therefore the existing ones.
 */
import { useEffect, useRef, useState } from 'react';

import type { PageChart } from '@/gen/edify/screens/v1/page_pb';
import { chartPayload, loadChartSystem } from '@/lib/legacyChart';

export function FeedChart({ chart }: { chart: PageChart }) {
  const plot = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  // The payload as text, so a new answer with the same figures does not redraw.
  const payload = JSON.stringify(chartPayload(chart));
  useEffect(() => {
    let live = true;
    let drawn: { destroy?: () => void } | null = null;
    loadChartSystem()
      .then((system) => {
        if (!live || !plot.current) return;
        drawn = system.renderDetached(plot.current, system.formBase(JSON.parse(payload)));
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
      try {
        drawn?.destroy?.();
      } catch {
        // Already torn down with its slot.
      }
    };
  }, [payload]);
  return (
    <section className="card edify-data-chart" aria-label={chart.title || 'Chart'} data-block="chart">
      <header className="edify-data-chart__header" data-no-titlebar="">
        <h3 className="edify-data-chart__title">{chart.title}</h3>
        {chart.subtitle ? <p className="edify-data-chart__subtitle">{chart.subtitle}</p> : null}
      </header>
      <div className="edify-data-chart__plot" ref={plot} />
      {failed ? (
        <p className="edify-text-caption edify-text-muted" role="alert">
          This chart could not be drawn. Reload the page to try again.
        </p>
      ) : null}
    </section>
  );
}
