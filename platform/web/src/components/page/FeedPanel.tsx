/*
 * A titled card of parts in the order the page draws them (PagePanel): a
 * sub-heading, a paragraph, label/value fields, rows, links, a meter. The
 * Planning page's workload line and its empty states arrive as panels.
 */
import Link from 'next/link';

import type { PagePanel, PagePanelItem } from '@/gen/edify/screens/v1/page_pb';

import { Badge } from '../blocks/Badge';
import { textTone } from '../blocks/tones';

function Item({ item, resolve }: { item: PagePanelItem; resolve: (href: string) => string }) {
  const kind = item.kind;
  switch (kind.case) {
    case 'heading':
      return <h3 className="mt-2 text-[length:var(--edify-text-micro-size)] font-semibold text-[var(--edify-text-muted)] first:mt-0">{kind.value}</h3>;
    case 'text':
      return <p className={`text-[length:var(--edify-text-label-size)] font-medium ${textTone(item.tone)}`}>{kind.value}</p>;
    case 'fields':
      return (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {kind.value.facts.map((fact) => (
            <div key={fact.label} className="min-w-0">
              <dt className="text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{fact.label}</dt>
              <dd className={`font-medium ${textTone(fact.tone)}`}>{fact.value}</dd>
            </div>
          ))}
        </dl>
      );
    case 'rows':
      return (
        <ul className="divide-y divide-[var(--edify-table-divider)]">
          {kind.value.rows.map((row, index) => (
            <li key={index} className="flex items-center justify-between gap-3 py-1.5">
              <span className="min-w-0">
                <span className="block font-medium">{row.label}</span>
                {row.meta ? <span className="block text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{row.meta}</span> : null}
              </span>
              <span className={`shrink-0 font-semibold ${textTone(row.tone)}`}>{row.value}</span>
            </li>
          ))}
        </ul>
      );
    case 'links':
      return (
        <ul className="space-y-1">
          {kind.value.links.map((link, index) => {
            const href = resolve(link.href);
            return (
              <li key={index} className="text-[13px]">
                {href ? (
                  <Link href={href} className="font-semibold text-[var(--brand-primary-text)] underline dark:text-[var(--edify-accent-text)]">{link.text}</Link>
                ) : (
                  <span>{link.text}</span>
                )}
                {link.caption ? <span className="block text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{link.caption}</span> : null}
              </li>
            );
          })}
        </ul>
      );
    case 'meter': {
      const meter = kind.value;
      return (
        <div>
          <div className="flex justify-between text-[13px] font-medium"><span>{meter.label}</span><span>{meter.value}</span></div>
          <div className="mt-1 h-1.5 rounded-full bg-[var(--edify-surface-muted)]">
            <div className="h-1.5 rounded-full bg-[var(--brand-primary)]" style={{ width: `${Math.round(Math.min(Math.max(meter.fraction, 0), 1) * 100)}%` }} />
          </div>
        </div>
      );
    }
    default:
      return null;
  }
}

export function FeedPanel({ panel, resolve, nested = false }: { panel: PagePanel; resolve: (href: string) => string; nested?: boolean }) {
  return (
    <section
      aria-label={panel.title || undefined}
      data-block="panel"
      className={`rounded-[10px] border border-[var(--edify-border)] ${nested ? 'bg-[var(--edify-surface)] p-3' : 'bg-[var(--edify-card-surface)] px-4 py-3 shadow-[var(--edify-shadow-sm)]'}`}
    >
      {panel.title || panel.badges.length ? (
        <header className="mb-2 flex flex-wrap items-center gap-2">
          {panel.title ? <h2 className="text-[length:var(--edify-text-label-size)] font-bold">{panel.title}</h2> : null}
          {panel.subtitle ? <span className="text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{panel.subtitle}</span> : null}
          {panel.badges.map((badge) => (
            <Badge key={badge.text} tone={badge.tone} title={badge.title}>{badge.text}</Badge>
          ))}
        </header>
      ) : null}
      <div className="space-y-1.5">
        {panel.items.map((item, index) => (
          <Item key={index} item={item} resolve={resolve} />
        ))}
      </div>
    </section>
  );
}
