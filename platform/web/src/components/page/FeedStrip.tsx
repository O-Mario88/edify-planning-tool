/*
 * A page's figures (components/context_metrics.html and My Plan's
 * kpi_cards.html): one card of cells, each a label, its figure and the short
 * line under it. A strip with a line under its title (My Plan's "Plan
 * Breakdown by Period · All activity types combined") is a titled card of
 * its own on the existing page; the others carry their title for screen
 * readers only. On a phone the cells sit two a row, as there.
 */
import Link from 'next/link';

import type { PageStrip } from '@/gen/edify/screens/v1/page_pb';

import { textTone } from '../blocks/tones';

export function FeedStrip({ strip, resolve }: { strip: PageStrip; resolve: (href: string) => string }) {
  const titled = Boolean(strip.subtitle);
  const cells = (
    <dl className="grid grid-cols-2 divide-[var(--edify-border)] max-sm:[&>div:nth-child(odd)]:border-r max-sm:[&>div]:border-b max-sm:[&>div]:border-[var(--edify-border)] sm:flex sm:divide-x sm:overflow-x-auto">
      {strip.metrics.map((metric) => {
        const href = resolve(metric.href);
        return (
          <div key={metric.label} className="relative min-w-0 px-4 py-3 text-center sm:min-w-[8.5rem] sm:flex-1 sm:text-left" title={metric.note || undefined}>
            <dt className={`text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)] ${titled ? 'uppercase' : ''}`}>{metric.label}</dt>
            <dd className={`${titled ? 'text-[14px] font-semibold' : 'text-[1.4rem] font-bold leading-tight'} ${textTone(metric.tone)}`}>
              {href ? <Link href={href} className="hover:underline">{metric.value}</Link> : metric.value}
            </dd>
            {metric.helper ? <dd className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{metric.helper}</dd> : null}
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
    <section aria-label={strip.title || 'Figures'} data-block="strip" className="overflow-hidden rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-sm)]">
      {cells}
    </section>
  );
}
