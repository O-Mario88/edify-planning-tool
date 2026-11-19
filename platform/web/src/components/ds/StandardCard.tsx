/*
 * The design system's card: the existing web's registered card
 * (templates/components/registered_card.html): a surface with its title,
 * an optional "View all →" link at its head, its content, and an optional
 * link at its foot. Every card on a page that is not a table card or a
 * family of its own is this card.
 */
import Link from 'next/link';
import type { ReactNode } from 'react';

import { CardTitle } from './Typography';

export interface CardLink {
  readonly label: string;
  readonly href: string;
}

export function StandardCard({
  title,
  id,
  headLink,
  footLink,
  children,
}: {
  title: string;
  id?: string;
  headLink?: CardLink;
  footLink?: CardLink;
  children: ReactNode;
}) {
  const titleId = id ? `card-${id}-title` : undefined;
  return (
    <section
      className="edify-surface rounded-surface border border-[var(--edify-border)] shadow-sm p-5 space-y-3 edify-structured-surface"
      data-component-type="card"
      aria-labelledby={titleId}
      aria-label={titleId ? undefined : title}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle id={titleId}>{title}</CardTitle>
        </div>
        {headLink ? (
          <Link href={headLink.href} className="shrink-0 edify-text-caption font-semibold edify-primary-text hover:underline">
            {headLink.label} &rarr;
          </Link>
        ) : null}
      </header>
      {children}
      {footLink ? (
        <Link href={footLink.href} className="inline-block edify-text-caption font-semibold edify-primary-text hover:underline">
          {footLink.label} &rarr;
        </Link>
      ) : null}
    </section>
  );
}
