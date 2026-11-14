/*
 * The profile's insights rail (partials/profiles/_rail.html, the owner's
 * right-hand rail, 2026-10-10): a title, then parts, each a figure with its
 * note, meters out of their scale, a note and links with a chevron.
 */
import Link from 'next/link';

import type { PageRail, PageRailPart } from '@/gen/edify/screens/v1/page_pb';

import { Icon } from '../shell/icons';

type Resolve = (href: string) => string;

function Part({ part, resolve }: { part: PageRailPart; resolve: Resolve }) {
  const figureHref = resolve(part.figureHref);
  return (
    <section data-rail-part={part.key} className="rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface-muted)] p-3 lg:border-0 lg:bg-transparent lg:p-0">
      <h3 className="text-[length:var(--edify-text-label-size)] font-bold">{part.title}</h3>
      {part.figure ? (
        <p className="text-[1.6rem] font-bold leading-tight">
          {figureHref ? <Link href={figureHref} className="hover:underline">{part.figure}</Link> : part.figure}
        </p>
      ) : null}
      {part.figureNote ? <p className="text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{part.figureNote}</p> : null}
      {part.meters.length ? (
        <ul className="mt-2 divide-y divide-[var(--edify-table-divider)]">
          {part.meters.map((meter) => {
            const href = resolve(meter.href);
            const label = href ? <Link href={href} className="hover:underline">{meter.label}</Link> : meter.label;
            return (
              <li key={meter.label} className="grid grid-cols-[minmax(0,1fr)_4.5rem_2.25rem] items-center gap-3 py-1.5 text-[13px] font-medium">
                <span className="min-w-0">{label}</span>
                <span className="h-1.5 rounded-full bg-[var(--edify-border)]" aria-hidden="true">
                  <span className="block h-1.5 rounded-full bg-[var(--brand-primary)]" style={{ width: `${Math.round(Math.min(Math.max(meter.fraction, 0), 1) * 100)}%` }} />
                </span>
                <span className="text-right font-semibold">{meter.value}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
      {part.note ? <p className="mt-2 text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{part.note}</p> : null}
      {part.links.length ? (
        <ul className="mt-1 divide-y divide-[var(--edify-table-divider)]">
          {part.links.map((link) => {
            const href = resolve(link.href);
            const body = (
              <>
                <span aria-hidden="true" className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--edify-warning-text)]" />
                <span className="min-w-0 flex-1">
                  {link.text}
                  {link.caption ? <span className="block text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{link.caption}</span> : null}
                </span>
                {href ? <Icon name="chevronRight" className="mt-0.5 h-4 w-4 shrink-0" /> : null}
              </>
            );
            return (
              <li key={link.text} className="text-[13px] font-semibold">
                {href ? <Link href={href} className="flex gap-2 py-1.5 hover:underline">{body}</Link> : <span className="flex gap-2 py-1.5">{body}</span>}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

export function FeedRail({ rail, resolve }: { rail: PageRail; resolve: Resolve }) {
  return (
    <aside aria-label={rail.title || 'Insights'} data-block="rail" className="rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-sm)]">
      {rail.title ? <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{rail.title}</h2> : null}
      {rail.subtitle ? <p className="text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{rail.subtitle}</p> : null}
      <div className="mt-3 space-y-4 lg:divide-y lg:divide-[var(--edify-border)] lg:[&>section+section]:pt-4">
        {rail.parts.map((part) => (
          <Part key={part.key || part.title} part={part} resolve={resolve} />
        ))}
      </div>
    </aside>
  );
}
