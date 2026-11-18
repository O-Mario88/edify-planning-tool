/*
 * A page's figures as the existing web draws them: one context-metrics row
 * (templates/components/context_metrics.html, styled by the existing
 * stylesheets the root layout links), each fact its label, the figure and
 * the short line under it, a link where the figure opens one, and the
 * fuller sentence for a screen reader. Figures are the gateway's; nothing
 * is counted here.
 */
import Link from 'next/link';

import type { PageMetric, PageStrip } from '@/gen/edify/screens/v1/page_pb';

function FactBody({ metric }: { metric: PageMetric }) {
  return (
    <>
      <span className="sr-only">
        {metric.label}: {metric.value}.
      </span>
      <span className="context-metrics__label" aria-hidden="true">
        {metric.label}
      </span>
      <strong className="context-metrics__value" title={metric.value} aria-hidden="true">
        {metric.value}
      </strong>
      {metric.helper ? (
        <span className="context-metrics__helper" title={metric.note || metric.helper} data-tone={metric.tone}>
          {metric.helper}
        </span>
      ) : null}
      {metric.note ? (
        <span className="sr-only" data-kpi-note>
          {metric.note}
        </span>
      ) : null}
    </>
  );
}

function Fact({ metric, href }: { metric: PageMetric; href: string }) {
  return (
    <span className="context-metrics__fact" role="listitem" data-component="context-metric" title={metric.note || undefined}>
      {href ? (
        <Link href={href} className="context-metrics__link">
          <FactBody metric={metric} />
        </Link>
      ) : (
        <span className="context-metrics__text">
          <FactBody metric={metric} />
        </span>
      )}
    </span>
  );
}

export function FeedStrip({ strip, resolve }: { strip: PageStrip; resolve: (href: string) => string }) {
  if (!strip.metrics.length) return null;
  return (
    <section
      className="context-metrics"
      data-mobile-summary=""
      data-context-metrics=""
      data-kpi-count={strip.metrics.length}
      aria-label={strip.title || 'Performance overview'}
      data-block="strip"
    >
      {strip.title || strip.subtitle ? (
        <header className="context-metrics__header">
          {strip.title ? <h2 className="context-metrics__title">{strip.title}</h2> : null}
          {strip.subtitle ? <p className="context-metrics__subtitle">{strip.subtitle}</p> : null}
        </header>
      ) : null}
      <div className="context-metrics__sentence" role="list" tabIndex={0} aria-label="Performance metrics; scroll to explore">
        {strip.metrics.map((metric) => (
          <Fact key={metric.label} metric={metric} href={resolve(metric.href)} />
        ))}
      </div>
    </section>
  );
}
