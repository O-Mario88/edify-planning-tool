/*
 * A card of label/value facts in one row (the profile engine's facts strip,
 * partials/profiles/_facts.html): School ID, Type, District…; two a row on a
 * phone. A fact with a link opens that record's own page.
 */
import Link from 'next/link';

import type { PageFacts } from '@/gen/edify/screens/v1/page_pb';

import { textTone } from '../blocks/tones';

export function FeedFacts({ facts, resolve }: { facts: PageFacts; resolve: (href: string) => string }) {
  return (
    <section aria-label="Facts" data-block="facts" className="card px-4 py-3 shadow-[var(--edify-shadow-sm)]">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:flex sm:flex-wrap sm:gap-x-8">
        {facts.facts.map((fact) => {
          const href = resolve(fact.href);
          return (
            <div key={fact.label} className="min-w-0">
              <dt className="text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{fact.label}</dt>
              <dd className={`font-semibold ${textTone(fact.tone)}`}>
                {href ? <Link href={href} className="hover:underline">{fact.value}</Link> : fact.value}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
