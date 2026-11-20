/*
 * A page's figures as tiles (owner, 2026-11-20, after the Smart Route
 * Planner's figure cards: "more beautiful compared to the flat boring
 * tiles"): each a card with its figure's tinted icon, the figure, its
 * label and the line under it, the info mark where the figure has a note,
 * the whole card a link where the figure opens a page. The phone draws the
 * same tiles (phone/PhoneTiles), with the same icons and tints. Figures are
 * the gateway's; nothing is counted here.
 */
import { Info } from 'lucide-react';
import Link from 'next/link';

import type { PageMetric, PageStrip } from '@/gen/edify/screens/v1/page_pb';
import { figureIcon } from '@/lib/figureIcon';
import { foldFigures } from '@/lib/heroStrip';

import { FIGURE_ICONS, figureTint } from '../phone/PhoneTiles';
import { Icon } from '../shell/icons';
import type { FigureTint } from '../phone/PhoneTiles';

/** A tint's icon colour, and the colour its line under the label takes. */
const TINTS: Readonly<Record<FigureTint, { icon: string; line: string }>> = {
  success: { icon: 'var(--edify-success)', line: 'var(--edify-success-text)' },
  danger: { icon: 'var(--edify-danger)', line: 'var(--edify-danger-text)' },
  warning: { icon: 'var(--edify-warning)', line: 'var(--edify-warning-text)' },
  info: { icon: 'var(--edify-info)', line: 'var(--edify-info-text)' },
  primary: { icon: 'var(--edify-primary)', line: 'var(--edify-text-muted)' },
};

/** A tile's words never stack a word a line (2026-11-20): the tiles are at
 *  least this wide, and the info mark sits in the corner instead of taking a
 *  column from the label. */
const TILE =
  'relative flex items-center gap-4 rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-5 py-4 text-left no-underline shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_-14px_rgba(15,23,42,0.18)] transition-[box-shadow,border-color] duration-[180ms] motion-reduce:transition-none';
const LINKED =
  'hover:border-[var(--edify-border-strong)] hover:shadow-[0_1px_2px_rgba(15,23,42,0.06),0_12px_28px_-12px_rgba(15,23,42,0.24)] focus-visible:outline-2 focus-visible:outline-offset-2';

function Tile({ metric, href, hero = false }: { metric: PageMetric; href: string; hero?: boolean }) {
  const icon = figureIcon(metric.label);
  const Icon = FIGURE_ICONS[icon];
  const tint = TINTS[figureTint(metric, icon)];
  const body = (
    <>
      <span
        aria-hidden="true"
        className={hero ? 'grid h-14 w-14 shrink-0 place-items-center rounded-[14px]' : 'grid h-12 w-12 shrink-0 place-items-center rounded-[12px]'}
        style={{ background: `color-mix(in srgb, ${tint.icon} 12%, transparent)`, color: tint.icon }}
      >
        <Icon size={24} strokeWidth={1.75} />
      </span>
      <span className="min-w-0 flex-1">
        <span className={`block font-bold tracking-[-0.01em] text-[var(--edify-text)] tabular-nums ${hero ? 'text-[30px] leading-[36px]' : 'text-[22px] leading-[28px]'}`}>{metric.value}</span>
        <span className="block text-[13.7px] font-medium leading-[18px] text-[var(--edify-text-muted)]">{metric.label}</span>
        {metric.helper ? (
          <span className="mt-1 block text-[12px] font-semibold leading-[16px]" style={{ color: tint.line }}>
            {metric.helper}
          </span>
        ) : null}
      </span>
      {metric.note ? (
        <span className="absolute right-3 top-3 text-[var(--edify-text-subtle)]" title={metric.note}>
          <Info size={18} aria-hidden="true" />
          <span className="sr-only" data-kpi-note>
            {metric.note}
          </span>
        </span>
      ) : null}
    </>
  );
  return href ? (
    <Link href={href} className={`${TILE} ${LINKED}`} data-figure="" role="listitem">
      {body}
    </Link>
  ) : (
    <div className={TILE} data-figure="" role="listitem">
      {body}
    </div>
  );
}

interface FeedStripProps {
  strip: PageStrip;
  resolve: (href: string) => string;
  /** The page's hero figures (lib/heroStrip liftHeroes): larger, none folded. */
  hero?: boolean;
}

const TILE_GRID = 'grid grid-cols-[repeat(auto-fill,minmax(256px,1fr))] gap-4';

export function FeedStrip({ strip, resolve, hero = false }: FeedStripProps) {
  if (!strip.metrics.length) return null;
  // Every strip shows its main figures and folds the rest (owner, 2026-11-20:
  // "reduce the number of tiles and do it throughout the platform").
  const { shown, folded } = hero ? { shown: strip.metrics, folded: [] } : foldFigures(strip.metrics);
  const tile = (metric: PageMetric) => <Tile key={metric.label} metric={metric} href={metric.href ? resolve(metric.href) : ''} hero={hero} />;
  return (
    <section data-block="strip" data-kpi-count={strip.metrics.length} data-hero={hero || undefined} aria-label={strip.title || (hero ? 'What decides your work' : 'Performance overview')} className="space-y-3">
      {strip.title || strip.subtitle ? (
        <header>
          {strip.title ? <h2 className="text-[16px] font-bold text-[var(--edify-text)]">{strip.title}</h2> : null}
          {strip.subtitle ? <p className="text-[13px] text-[var(--edify-text-muted)]">{strip.subtitle}</p> : null}
        </header>
      ) : null}
      <div role="list" className={hero ? 'grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4' : TILE_GRID}>
        {shown.map(tile)}
      </div>
      {folded.length ? (
        <details className="group" data-figures-fold>
          <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 py-1 edify-text-caption font-semibold edify-primary-text [&::-webkit-details-marker]:hidden">
            <Icon name="chevronDown" className="h-4 w-4 transition-transform group-open:rotate-180" />
            <span>
              All figures ({strip.metrics.length})
            </span>
          </summary>
          <div role="list" className={`${TILE_GRID} pt-3`}>
            {folded.map(tile)}
          </div>
        </details>
      ) : null}
    </section>
  );
}
