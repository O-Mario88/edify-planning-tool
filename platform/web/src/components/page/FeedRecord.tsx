/*
 * A record card (PageRecord: Planning's Clusters tab, as the Clusters page
 * draws its cards): the name linking to its profile, its pills, one Actions
 * menu, and its facts.
 */
import Link from 'next/link';

import type { PageAction, PageRecord } from '@/gen/edify/screens/v1/page_pb';

import { Badge } from '../blocks/Badge';
import { RowActions } from '../blocks/RowActions';
import { textTone } from '../blocks/tones';

export function FeedRecord({ record, resolve, hrefOf }: { record: PageRecord; resolve: (href: string) => string; hrefOf: (action: PageAction) => string }) {
  const href = resolve(record.href);
  return (
    <article data-block="record" className="rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-4 py-3 shadow-[var(--edify-shadow-sm)]">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="min-w-0 text-[length:var(--edify-text-label-size)] font-bold">
          {href ? <Link href={href} className="hover:underline">{record.title}</Link> : record.title}
        </h2>
        {record.badges.map((badge) => (
          <Badge key={badge.text} tone={badge.tone} title={badge.title}>{badge.text}</Badge>
        ))}
        {record.subtitle ? <span className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{record.subtitle}</span> : null}
        <div className="ml-auto">
          <RowActions
            subject={record.title}
            actions={record.actions.map((action) => ({ key: `${action.key}:${action.label}`, label: action.label, enabled: action.enabled, reason: action.reason, href: hrefOf(action) }))}
          />
        </div>
      </header>
      {record.facts.length ? (
        <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--edify-text-label-size)]">
          {record.facts.map((fact) => {
            const factHref = resolve(fact.href);
            return (
              <div key={fact.label} className="flex min-w-0 gap-1">
                <dt className="font-medium text-[var(--edify-text-muted)]">{fact.label}:</dt>
                <dd className={`font-semibold ${textTone(fact.tone)}`}>{factHref ? <Link href={factHref} className="hover:underline">{fact.value}</Link> : fact.value}</dd>
              </div>
            );
          })}
        </dl>
      ) : null}
    </article>
  );
}
