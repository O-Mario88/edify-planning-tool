/*
 * A figure strip as the app's tiles (mobile/src/ui/page/PageStripView.tsx):
 * each a tinted icon, the figure, its label and the line under it, with an
 * info mark where the figure has a note. Two a row on a phone, compact there
 * (no icon box; phone.css), so every figure shows in a few rows; even rows
 * of at most five from a tablet up.
 */
import type { CSSProperties } from 'react';
import type { LucideIcon } from 'lucide-react';
import { Banknote, Calendar, CalendarCheck, ChartColumn, Clock, GraduationCap, Info, LayoutGrid, Route, School, TriangleAlert, Users } from 'lucide-react';

import type { PageMetric, PageStrip } from '@/gen/edify/screens/v1/page_pb';
import { figureIcon } from '@/lib/figureIcon';
import type { FigureIconName } from '@/lib/figureIcon';

import { phoneTone, tileColumns } from './tone';

const ICONS: Readonly<Record<FigureIconName, LucideIcon>> = {
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

/** A tile's tint: its tone where it has one, else what its icon says. */
function tintOf(metric: PageMetric, icon: FigureIconName): string {
  const tone = phoneTone(metric.tone);
  if (tone === 'good') return 'var(--ph-success)';
  if (tone === 'alert') return 'var(--ph-danger)';
  if (tone === 'caution') return 'var(--ph-warning)';
  if (tone === 'info') return 'var(--ph-link)';
  if (icon === 'alert') return 'var(--ph-danger)';
  if (icon === 'check') return 'var(--ph-success)';
  return 'var(--ph-primary)';
}

function Tile({ metric, resolve }: { metric: PageMetric; resolve: (href: string) => string }) {
  const icon = figureIcon(metric.label);
  const Icon = ICONS[icon];
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
  const style = { '--ph-tint': tintOf(metric, icon) } as CSSProperties;
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

export function PhoneTiles({ strip, resolve }: { strip: PageStrip; resolve: (href: string) => string }) {
  const count = strip.metrics.length;
  const style = { '--ph-columns': tileColumns(count, false), '--ph-wide-columns': tileColumns(count, true) } as CSSProperties;
  const tiles = (
    <div data-ph="tiles" role="group" aria-label={strip.title || undefined} style={style}>
      {strip.metrics.map((metric) => (
        <Tile key={metric.label} metric={metric} resolve={resolve} />
      ))}
    </div>
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
