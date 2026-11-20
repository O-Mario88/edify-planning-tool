/*
 * A figure strip as the app's tiles (mobile/src/ui/page/PageStripView.tsx):
 * each a tinted icon, the figure, its label and the line under it, with an
 * info mark where the figure has a note. Two a row on a phone, compact there
 * (no icon box; phone.css), so every figure shows in a few rows; even rows
 * of at most five from a tablet up.
 */
import type { CSSProperties } from 'react';
import type { LucideIcon } from 'lucide-react';
import { Banknote, Calendar, CalendarCheck, ChartColumn, ChevronDown, Clock, GraduationCap, Info, LayoutGrid, Route, School, TriangleAlert, Users } from 'lucide-react';

import type { PageMetric, PageStrip } from '@/gen/edify/screens/v1/page_pb';
import { figureIcon } from '@/lib/figureIcon';
import { foldFigures } from '@/lib/heroStrip';
import type { FigureIconName } from '@/lib/figureIcon';

import { phoneTone, tileColumns } from './tone';

/** A figure's icon by what its label names (lib/figureIcon), for every
 *  tile: the phone's here and the desktop's (page/FeedStrip). */
export const FIGURE_ICONS: Readonly<Record<FigureIconName, LucideIcon>> = {
  school: School,
  cluster: LayoutGrid,
  route: Route,
  clock: Clock,
  calendar: Calendar,
  check: CalendarCheck,
  alert: TriangleAlert,
  money: Banknote,
  people: Users,
  training: GraduationCap,
  chart: ChartColumn,
};

export type FigureTint = 'success' | 'danger' | 'warning' | 'info' | 'primary';

/** A tile's tint: its tone where it has one, else what its icon says. */
export function figureTint(metric: PageMetric, icon: FigureIconName): FigureTint {
  const tone = phoneTone(metric.tone);
  if (tone === 'good') return 'success';
  if (tone === 'alert') return 'danger';
  if (tone === 'caution') return 'warning';
  if (tone === 'info') return 'info';
  if (icon === 'alert') return 'danger';
  if (icon === 'check') return 'success';
  return 'primary';
}

const PHONE_TINT: Readonly<Record<FigureTint, string>> = {
  success: 'var(--ph-success)',
  danger: 'var(--ph-danger)',
  warning: 'var(--ph-warning)',
  info: 'var(--ph-link)',
  primary: 'var(--ph-primary)',
};

function Tile({ metric, resolve }: { metric: PageMetric; resolve: (href: string) => string }) {
  const icon = figureIcon(metric.label);
  const Icon = FIGURE_ICONS[icon];
  const tone = phoneTone(metric.tone);
  const body = (
    <>
      <span data-ph="tile-icon" aria-hidden="true">
        <Icon size={20} />
      </span>
      <span data-ph="tile-words">
        <span data-ph="tile-value" data-ph-tone={tone && tone !== 'brand' ? tone : undefined}>
          {metric.value}
        </span>
        <span data-ph="tile-label">{metric.label}</span>
        {metric.helper ? <span data-ph="tile-helper">{metric.helper}</span> : null}
      </span>
      {metric.note ? (
        <span data-ph="tile-info" title={metric.note}>
          <Info size={16} aria-label={metric.note} />
        </span>
      ) : null}
    </>
  );
  const style = { '--ph-tint': PHONE_TINT[figureTint(metric, icon)] } as CSSProperties;
  return metric.href ? (
    <a data-ph="tile" data-noted={metric.note ? true : undefined} href={resolve(metric.href)} style={style}>
      {body}
    </a>
  ) : (
    <div data-ph="tile" data-noted={metric.note ? true : undefined} style={style}>
      {body}
    </div>
  );
}

interface PhoneTilesProps {
  strip: PageStrip;
  resolve: (href: string) => string;
  /** The page's hero figures (lib/heroStrip liftHeroes): larger, none folded. */
  hero?: boolean;
  /** The page, which may name the figures it keeps in view (FIGURES_IN_VIEW_BY_PAGE). */
  pagePath?: string;
}

export function PhoneTiles({ strip, resolve, hero = false, pagePath = '' }: PhoneTilesProps) {
  // Every strip shows its main figures and folds the rest (owner, 2026-11-20:
  // "reduce the number of tiles and do it throughout the platform").
  const { shown, folded } = hero ? { shown: strip.metrics, folded: [] } : foldFigures(strip.metrics, pagePath);
  const grid = (metrics: readonly PageMetric[], label?: string) => (
    <div
      data-ph="tiles"
      data-hero={hero || undefined}
      role="group"
      aria-label={label}
      style={{ '--ph-columns': tileColumns(metrics.length, false), '--ph-wide-columns': tileColumns(metrics.length, true) } as CSSProperties}
    >
      {metrics.map((metric) => (
        <Tile key={metric.label} metric={metric} resolve={resolve} />
      ))}
    </div>
  );
  const tiles = folded.length ? (
    <div data-ph="tiles-folded">
      {grid(shown, strip.title || undefined)}
      <details data-ph="explain" data-bare>
        <summary data-ph="explain-toggle">
          <ChevronDown aria-hidden="true" size={16} data-ph="explain-chevron" />
          <span>All figures ({strip.metrics.length})</span>
        </summary>
        {grid(folded, 'More figures')}
      </details>
    </div>
  ) : (
    grid(shown, strip.title || undefined)
  );
  if (!strip.subtitle) return tiles;
  return (
    <section data-ph="tiles-card" aria-label={strip.title}>
      <div>
        <h2 data-ph="tiles-title">{strip.title}</h2>
        <p data-ph="tiles-subtitle">{strip.subtitle}</p>
      </div>
      {tiles}
    </section>
  );
}
