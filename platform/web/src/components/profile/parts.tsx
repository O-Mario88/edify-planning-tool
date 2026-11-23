/*
 * The School and Cluster Profile's shared pieces: the titled card, the figure
 * tile, the small figure row and the labelled panel lines. Every word and
 * figure is passed in from the gateway's answer; these only draw it.
 */
import { ChevronRight } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import './profile.css';

import type { PageMetric, PagePanel } from '@/gen/edify/screens/v1/page_pb';
import { resolveHref } from '@/lib/feedPage';
import { metricLine, panelLine } from '@/lib/schoolProfileView';

export type Accent = 'blue' | 'green' | 'violet' | 'amber';

/** A figure longer than this ("Not Assessed", "UGX 1,500,000") is set smaller so it stays inside its tile. */
const LONG_FIGURE = 7;

const ACCENT_TILE: Readonly<Record<Accent, string>> = {
  blue: 'bg-[color-mix(in_srgb,var(--brand-primary)_5%,var(--edify-surface))] border-[color-mix(in_srgb,var(--brand-primary)_16%,var(--edify-border))]',
  green: 'bg-[color-mix(in_srgb,var(--edify-success)_7%,var(--edify-surface))] border-[color-mix(in_srgb,var(--edify-success)_24%,var(--edify-border))]',
  violet: 'bg-[color-mix(in_srgb,#7c3aed_5%,var(--edify-surface))] border-[color-mix(in_srgb,#7c3aed_16%,var(--edify-border))]',
  amber: 'bg-[color-mix(in_srgb,var(--edify-warning)_7%,var(--edify-surface))] border-[color-mix(in_srgb,var(--edify-warning)_24%,var(--edify-border))]',
};

const ACCENT_ICON: Readonly<Record<Accent, string>> = {
  blue: 'bg-[color-mix(in_srgb,var(--brand-primary)_12%,transparent)] text-[var(--brand-primary)]',
  green: 'bg-[color-mix(in_srgb,var(--edify-success)_14%,transparent)] text-[var(--edify-success-text)]',
  violet: 'bg-[color-mix(in_srgb,#7c3aed_12%,transparent)] text-violet-700 dark:text-violet-300',
  amber: 'bg-[color-mix(in_srgb,var(--edify-warning)_16%,transparent)] text-[var(--edify-warning-text)]',
};

interface ProfileCardProps {
  readonly title: string;
  readonly icon: LucideIcon;
  /** The small words beside the title ("FY 2026/27"). */
  readonly aside?: ReactNode;
  readonly className?: string;
  readonly block?: string;
  /** Where the card sits in the page's layout (profile.css). */
  readonly area?: string;
  /** The card has its row to itself. */
  readonly alone?: boolean;
  readonly children: ReactNode;
}

export function ProfileCard({ title, icon: CardIcon, aside, className = '', block, area, alone = false, children }: ProfileCardProps) {
  return (
    <section data-block={block ?? 'profile-card'} data-pf-card={area} data-alone={alone ? '' : undefined} aria-label={title} className={`card min-w-0 p-4 ${className}`}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
        <h2 className="flex items-center gap-2 whitespace-nowrap text-[16px] font-bold leading-tight text-[var(--edify-text)]">
          <CardIcon className="h-[18px] w-[18px] shrink-0 text-[var(--brand-primary)]" aria-hidden="true" />
          <span>{title}</span>
        </h2>
        {aside ? <div data-pf="card-aside" className="shrink-0 text-[12px] font-medium text-[var(--edify-text-muted)]">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

interface MetricTileProps {
  readonly metric: PageMetric;
  readonly icon: LucideIcon;
  readonly accent: Accent;
  readonly pagePath: string;
  /** On a phone the tile reads as one row (icon, figure, words, chevron). */
  readonly rowOnPhone?: boolean;
}

export function MetricTile({ metric, icon: TileIcon, accent, pagePath, rowOnPhone = false }: MetricTileProps) {
  const href = resolveHref(pagePath, metric.href);
  const line = metricLine(metric);
  const body = (
    <>
      <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-[8px] ${ACCENT_ICON[accent]}`}>
        <TileIcon className="h-[18px] w-[18px]" aria-hidden="true" />
      </span>
      <div data-pf="tile-text">
        <div className={`${metric.value.length > LONG_FIGURE ? 'text-[16px]' : 'text-[21px]'} font-bold leading-tight tabular-nums text-[var(--edify-text)] [overflow-wrap:anywhere]`}>{metric.value}</div>
        <div className="min-w-0">
          <div className="text-[13px] font-semibold leading-snug text-[var(--edify-text)]">{metric.label}</div>
          {line ? <div className="text-[12px] leading-snug text-[var(--edify-text-muted)]">{line}</div> : null}
        </div>
      </div>
      {rowOnPhone && href ? <span data-pf="tile-chevron"><ChevronRight className="h-4 w-4 text-[var(--edify-text-muted)]" aria-hidden="true" /></span> : null}
    </>
  );
  const shape = `rounded-[10px] border p-3 ${ACCENT_TILE[accent]}`;
  const layout = { 'data-pf': 'tile', 'data-row': rowOnPhone ? '' : undefined };
  if (!href) return <div {...layout} className={shape} title={metric.note || undefined}>{body}</div>;
  return (
    <Link {...layout} href={href} title={metric.note || undefined} className={`${shape} transition-colors hover:border-[var(--brand-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-primary)]`}>
      {body}
    </Link>
  );
}

/** The strip's other figures, opened from the card's header so the card keeps the design's height and none is lost. */
export function MoreFigures({ metrics, pagePath, extra }: { metrics: readonly PageMetric[]; pagePath: string; extra?: ReactNode }) {
  if (!metrics.length && !extra) return null;
  const words = `${metrics.length} more figure${metrics.length === 1 ? '' : 's'}`;
  return (
    <details data-pf="more-wrap">
      <summary aria-label={words} title={words}>+{metrics.length}</summary>
      <div data-pf="more-pop">
      {extra}
    <ul data-pf="more">
      {metrics.map((metric) => {
        const href = resolveHref(pagePath, metric.href);
        const content = (
          <>
            <span className="min-w-0 truncate text-[var(--edify-text-muted)]">{metric.label}</span>
            <span className="shrink-0 font-bold tabular-nums text-[var(--edify-text)]">{metric.value}</span>
          </>
        );
        const shape = 'flex items-baseline justify-between gap-2 py-1 text-[13px]';
        return (
          <li key={metric.label} title={metricLine(metric) || undefined}>
            {href ? <Link href={href} className={`${shape} hover:underline`}>{content}</Link> : <span className={shape}>{content}</span>}
          </li>
        );
      })}
    </ul>
      </div>
    </details>
  );
}

/** A Go panel's lines as labelled rows, with its links; a sentence with no label stays whole. */
export function PanelLines({ panel, pagePath }: { panel: PagePanel; pagePath: string }) {
  return (
    <div className="divide-y divide-[var(--edify-border)] text-[13px]">
      {panel.items.map((item, index) => {
        if (item.kind.case === 'text') {
          const { label, value } = panelLine(item.kind.value);
          return (
            <p key={index} className={label ? 'flex items-baseline justify-between gap-4 py-2' : 'py-2 text-[var(--edify-text-muted)]'}>
              {label ? <span className="min-w-0 font-semibold text-[var(--edify-text)]">{label}</span> : null}
              <span className={label ? 'min-w-0 text-right text-[var(--edify-text)]' : ''}>{value}</span>
            </p>
          );
        }
        if (item.kind.case === 'links') {
          return (
            <ul key={index} className="py-1">
              {item.kind.value.links.map((link) => {
                const href = resolveHref(pagePath, link.href);
                return (
                  <li key={link.text}>
                    {href ? (
                      <Link href={href} className="flex items-center justify-between gap-2 py-1.5 font-medium text-[var(--brand-primary)] hover:underline">
                        <span>{link.text}</span>
                        <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />
                      </Link>
                    ) : (
                      <span className="block py-1.5 text-[var(--edify-text)]">{link.text}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          );
        }
        if (item.kind.case === 'heading') return <h3 key={index} className="py-2 font-bold text-[var(--edify-text)]">{item.kind.value}</h3>;
        return null;
      })}
    </div>
  );
}
