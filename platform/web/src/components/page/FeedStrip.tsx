/*
 * A page's figures as separate tiles (owner, 2026-11-16: "the last image of
 * tiles reference is what I want for the entire platform", the Smart Route
 * Planner's figure cards): each tile a tinted icon, the figure, its label,
 * the short line under it and, where the figure has a note, an info dot that
 * says it. Tiles wrap into even rows of at most five on a wide screen; two
 * a row on a phone, where the icon is left out. A strip with a line under
 * its title (My Plan's "Plan Breakdown by Period · All activity types
 * combined") is a titled card of its own on the existing page; the others
 * carry their title for screen readers only.
 */
import Link from 'next/link';
import type { CSSProperties } from 'react';

import type { PageMetric, PageStrip } from '@/gen/edify/screens/v1/page_pb';
import { figureIcon } from '@/lib/figureIcon';
import type { FigureIconName } from '@/lib/figureIcon';

import { textTone } from '../blocks/tones';

const PATHS: Readonly<Record<FigureIconName, string>> = {
  school: 'M3 21h18M5 21V10m4 11V10m6 11V10m4 11V10M2 10h20L12 3 2 10z',
  cluster: 'M4 5h6v6H4V5zm10 0h6v6h-6V5zM4 15h6v6H4v-6zm10 0h6v6h-6v-6z',
  route: 'M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm12-10a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 17h7a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h7',
  clock: 'M12 7v5l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0z',
  calendar: 'M8 3v4m8-4v4M3 9h18M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z',
  check: 'M8 3v4m8-4v4M3 9h18M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm4 9 2 2 4-4',
  alert: 'M12 9v4m0 4h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  money: 'M3 7h18v10H3V7zm9 7.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM6 10v4m12-4v4',
  people: 'M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1m20 0v-1a4 4 0 0 0-3-3.9M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7-6a3 3 0 0 1 0 6',
  training: 'M2 7l10-4 10 4-10 4L2 7zm4 2v5c0 1.7 2.7 3 6 3s6-1.3 6-3V9m4-2v6',
  chart: 'M4 20V10m6 10V4m6 16v-7m4 7H2',
};

/** The tile's tint: its tone where it has one, else what the icon says. */
const TONE_TINT: Readonly<Record<string, string>> = {
  danger: '#dc2626',
  alert: '#dc2626',
  rose: '#dc2626',
  warning: '#d97706',
  caution: '#d97706',
  attention: '#d97706',
  amber: '#d97706',
  success: '#16a34a',
  positive: '#16a34a',
  good: '#16a34a',
  green: '#16a34a',
};
const ICON_TINT: Readonly<Partial<Record<FigureIconName, string>>> = { alert: '#dc2626', check: '#16a34a', money: '#d97706' };
const BLUE = '#1d6fe0';

function tintOf(metric: PageMetric, icon: FigureIconName): string {
  return TONE_TINT[metric.tone] ?? ICON_TINT[icon] ?? BLUE;
}

function FigureIcon({ name }: { name: FigureIconName }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} aria-hidden="true" className="h-6 w-6">
      <path strokeLinecap="round" strokeLinejoin="round" d={PATHS[name]} />
    </svg>
  );
}

function InfoDot({ text }: { text: string }) {
  return (
    <span className="mt-1 shrink-0 cursor-help text-[var(--edify-text-muted)] opacity-70" title={text} role="img" aria-label={text}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} aria-hidden="true" className="h-[18px] w-[18px]">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 16v-4m0-4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
      </svg>
    </span>
  );
}

function Tile({ metric, href }: { metric: PageMetric; href: string }) {
  const icon = figureIcon(metric.label);
  const tint = tintOf(metric, icon);
  return (
    <div className="flex min-w-0 items-start gap-3 rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-3 py-3 shadow-[var(--edify-shadow-sm)] sm:gap-4 sm:px-4 sm:py-4" data-tile={icon}>
      <span className="hidden h-12 w-12 shrink-0 place-items-center rounded-[12px] sm:grid" style={{ background: `${tint}1a`, color: tint }}>
        <FigureIcon name={icon} />
      </span>
      <dl className="flex min-w-0 flex-1 flex-col">
        <dd className={`order-1 text-[20px] font-bold leading-tight sm:text-[22px] ${textTone(metric.tone) || 'text-[var(--edify-text)]'}`}>
          {href ? <Link href={href} className="hover:underline">{metric.value}</Link> : metric.value}
        </dd>
        <dt className="order-2 text-[13px] text-[var(--edify-text-muted)] sm:text-[14px]">{metric.label}</dt>
        {metric.helper ? <dd className="order-3 mt-0.5 text-[12px] text-[var(--edify-text-muted)]">{metric.helper}</dd> : null}
        {metric.note && !metric.helper ? <dd className="sr-only">{metric.note}</dd> : null}
      </dl>
      {metric.note ? <InfoDot text={metric.note} /> : null}
    </div>
  );
}

/** At most this many tiles share a wide row. */
const MAX_ROW = 5;

/** A wide screen's columns: rows as even as they can be (10 → 5 + 5, 8 → 4 + 4). */
export function tileColumns(count: number): number {
  if (count <= 1) return 1;
  const rows = Math.ceil(count / MAX_ROW);
  return Math.ceil(count / rows);
}

export function FeedStrip({ strip, resolve }: { strip: PageStrip; resolve: (href: string) => string }) {
  const tiles = (
    <div
      className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-[repeat(auto-fit,minmax(13.5rem,1fr))] lg:grid-cols-[repeat(var(--tile-columns),minmax(0,1fr))]"
      style={{ '--tile-columns': tileColumns(strip.metrics.length) } as CSSProperties}
    >
      {strip.metrics.map((metric) => (
        <Tile key={metric.label} metric={metric} href={resolve(metric.href)} />
      ))}
    </div>
  );
  if (strip.subtitle) {
    return (
      <section aria-label={strip.title} data-block="strip" className="rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-sm)]">
        <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{strip.title}</h2>
        <p className="mb-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text-muted)]">{strip.subtitle}</p>
        {tiles}
      </section>
    );
  }
  return (
    <section aria-label={strip.title || 'Figures'} data-block="strip">
      {tiles}
    </section>
  );
}
