/*
 * A KPI strip: one card divided into cells, each a label, a big figure and
 * an optional muted helper (components/context_metrics.html). Figures are
 * the gateway's; nothing is counted here.
 */
import type { PageStrip } from '@/gen/edify/screens/v1/page_pb';

import { textTone } from './tones';

export function KpiStrip({ strip }: { strip: PageStrip }) {
  return (
    <section aria-label={strip.title || 'Figures'} data-block="strip" className="overflow-x-auto rounded-[var(--radius-surface)] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-sm)]">
      <dl className="flex min-w-max divide-x divide-[var(--edify-border)]">
        {strip.metrics.map((metric) => (
          <div key={metric.label} className="min-w-[8.5rem] flex-1 px-4 py-3">
            <dt className="text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{metric.label}</dt>
            <dd className={`text-[1.4rem] font-bold leading-tight ${textTone(metric.tone)}`}>
              {metric.href ? <a href={metric.href} className="hover:underline">{metric.value}</a> : metric.value}
            </dd>
            {metric.helper ? <dd className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{metric.helper}</dd> : null}
          </div>
        ))}
      </dl>
    </section>
  );
}
