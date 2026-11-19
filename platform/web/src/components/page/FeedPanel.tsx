/*
 * A titled card of parts in the order the page draws them (PagePanel): a
 * sub-heading, a paragraph, label/value fields, rows, links, a meter. The
 * Planning page's workload line and its empty states arrive as panels.
 */
import Link from 'next/link';
import { Fragment } from 'react';
import type { ReactNode } from 'react';

import type { PagePanel, PagePanelItem } from '@/gen/edify/screens/v1/page_pb';
import { noteTone, sentenceParts } from '@/lib/sentence';

import { Badge } from '../blocks/Badge';
import { textTone } from '../blocks/tones';

/** A paragraph read whole: its bold opening, its links at their words. */
function Sentence({ item, text, resolve }: { item: PagePanelItem; text: string; resolve: (href: string) => string }) {
  const parts = sentenceParts(text, item.lead, item.textLinks);
  const plain = Boolean(item.lead || item.textLinks.length);
  return (
    <p className={`text-[length:var(--edify-text-label-size)] font-medium ${plain ? '' : textTone(item.tone)}`}>
      {parts.map((part, index) => {
        if (part.kind === 'lead') return <strong key={index} className="font-bold">{part.text}</strong>;
        const href = part.kind === 'link' ? resolve(part.href) : '';
        if (href) {
          return (
            <Link key={index} href={href} className="font-semibold text-[var(--brand-primary-text)] underline underline-offset-2 dark:text-[var(--edify-accent-text)]">
              {part.text}
            </Link>
          );
        }
        return <Fragment key={index}>{part.text}</Fragment>;
      })}
    </p>
  );
}

function Item({ item, resolve, drawerHref }: { item: PagePanelItem; resolve: (href: string) => string; drawerHref: string }) {
  const kind = item.kind;
  switch (kind.case) {
    case 'heading':
      return <h3 className="mt-2 text-[length:var(--edify-text-micro-size)] font-semibold text-[var(--edify-text-muted)] first:mt-0">{kind.value}</h3>;
    case 'text':
      return <Sentence item={item} text={kind.value} resolve={resolve} />;
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
            // A drawer is never opened from here (some write when opened): its page on the existing web.
            const href = link.drawer ? drawerHref : resolve(link.href);
            return (
              <li key={index} className="text-[13px]">
                {href && link.drawer ? (
                  <a href={href} className="font-semibold text-[var(--brand-primary-text)] underline dark:text-[var(--edify-accent-text)]">{link.text}</a>
                ) : href ? (
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

/** A note's tint and accent edge, by its tone (the existing .edify-note). */
const NOTE: Readonly<Record<string, string>> = {
  info: '[--note:var(--edify-accent)]',
  warning: '[--note:var(--edify-warning-text)]',
  danger: '[--note:var(--edify-danger-text)]',
  success: '[--note:var(--edify-success-text)]',
};

export interface FeedPanelProps {
  readonly panel: PagePanel;
  readonly resolve: (href: string) => string;
  readonly drawerHref?: string;
  readonly nested?: boolean;
  /** The list's pager strip, drawn at the card's foot when the panel is a list's empty state. */
  readonly footer?: ReactNode;
}

export function FeedPanel({ panel, resolve, drawerHref = '', nested = false, footer }: FeedPanelProps) {
  const items = panel.items.map((item, index) => <Item key={index} item={item} resolve={resolve} drawerHref={drawerHref} />);
  const note = noteTone(panel);
  if (note && !footer) {
    // A note (the workload line, My Plan's past-due line): tinted, with a tone edge.
    return (
      <section
        data-block="note"
        role="status"
        className={`${NOTE[note] ?? NOTE.info} rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--note)_28%,transparent)] border-l-[3px] border-l-[color-mix(in_srgb,var(--note)_62%,transparent)] bg-[color-mix(in_srgb,var(--note)_7%,var(--edify-surface))] px-4 py-3`}
      >
        <div className="space-y-1.5">{items}</div>
      </section>
    );
  }
  if (footer) {
    // A list's empty state: its message centred over the pager strip, in one card.
    return (
      <section data-block="panel" data-empty className="overflow-hidden card">
        <div className="space-y-1 px-6 py-8 text-center font-semibold text-[var(--edify-text-muted)] [&>p:first-child]:text-[var(--edify-text)] [&>p+p]:font-medium">{items}</div>
        {footer}
      </section>
    );
  }
  // Loose text with no heading of its own (a section's intro line: the
  // Admin dashboard's "Use the business workspaces …") is text on the page
  // on the existing web, not a card.
  if (!nested && !panel.title && !panel.badges.length && panel.items.length && panel.items.every((item) => item.kind.case === 'text')) {
    return (
      <div data-block="panel" data-loose-text="" className="space-y-1 edify-text-caption edify-text-muted">
        {items}
      </div>
    );
  }
  return (
    <section
      aria-label={panel.title || undefined}
      data-block="panel"
      className={nested ? 'rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)] p-3' : 'card px-4 py-3'}
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
      <div className="space-y-1.5">{items}</div>
    </section>
  );
}
