/*
 * A page's figures (components/context_metrics.html and My Plan's
 * kpi_cards.html): one card of cells, each a label, its figure and the short
 * line under it. A strip with a line under its title (My Plan's "Plan
 * Breakdown by Period · All activity types combined") is a titled card of
 * its own on the existing page; the others carry their title for screen
 * readers only. The layout is the existing strip's (globals.css .edify-strip):
 * two a row on a phone, four from 37.5rem; one row on a rail (StripRail) from
 * 48rem; from 64rem eight or fewer share the row and nine or more scroll.
 */
import Link from 'next/link';

import type { PageStrip } from '@/gen/edify/screens/v1/page_pb';

import { textTone } from '../blocks/tones';
import { StripRail } from './StripRail';

export function FeedStrip({ strip, resolve }: { strip: PageStrip; resolve: (href: string) => string }) {
  const titled = Boolean(strip.subtitle);
  const cells = (
    <dl className="edify-strip">
      {strip.metrics.map((metric) => {
        const href = resolve(metric.href);
        return (
          <div key={metric.label} className="relative px-4 py-[10px]" title={metric.note || undefined}>
            <dt className={`edify-strip__label text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)] ${titled ? 'uppercase' : ''}`}>{metric.label}</dt>
            <dd className={`edify-strip__value ${titled ? 'text-[14px] font-semibold' : 'text-[1.4rem] font-bold leading-tight'} ${textTone(metric.tone)}`}>
              {href ? <Link href={href} className="hover:underline">{metric.value}</Link> : metric.value}
            </dd>
            {metric.helper ? <dd className="edify-strip__helper text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{metric.helper}</dd> : null}
            {metric.note && !metric.helper ? <dd className="sr-only">{metric.note}</dd> : null}
          </div>
        );
      })}
    </dl>
  );
  if (titled) {
    return (
      <section aria-label={strip.title} data-block="strip" className="rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-sm)]">
        <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{strip.title}</h2>
        <p className="mb-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text-muted)]">{strip.subtitle}</p>
        <div className="rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)]">{cells}</div>
      </section>
    );
  }
  return (
    <section aria-label={strip.title || 'Figures'} data-block="strip">
      <StripRail count={strip.metrics.length}>{cells}</StripRail>
    </section>
  );
}
