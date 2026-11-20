/*
 * The links that step through periods ("‹ Previous week", "This week",
 * "Next week ›") as one segmented control, not a column of underlined links
 * (owner, 2026-11-20: "make it more professional"). Straight dividers and
 * curved ends, as the platform's tabs. lib/presentBlocks.isStepper decides
 * which links are a stepper.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react';
import Link from 'next/link';

import type { PageLink } from '@/gen/edify/screens/v1/page_pb';
import { stepOf } from '@/lib/presentBlocks';

const DESKTOP_STEP =
  'inline-flex h-8 items-center gap-1 whitespace-nowrap px-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)] ' +
  'no-underline transition-colors hover:bg-[var(--edify-surface-muted)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] ' +
  'focus-visible:outline-[var(--brand-primary)] [&+&]:border-l [&+&]:border-[var(--edify-border)]';

export function PeriodStepper({ links, resolve, phone = false }: { links: readonly PageLink[]; resolve: (href: string) => string; phone?: boolean }) {
  // Keyed by place and words: from last week, "This week" and "Next week" share an href.
  const steps = links.map((link) => ({ link, ...stepOf(link) }));
  if (phone) {
    return (
      <nav data-ph="stepper" aria-label="Choose the period">
        {steps.map(({ link, words, way }, index) => (
          <a key={`${index}-${words}`} data-ph="step" data-way={way} href={resolve(link.href)}>
            {way === 'back' ? <ChevronLeft size={16} aria-hidden="true" /> : null}
            <span>{words}</span>
            {way === 'forward' ? <ChevronRight size={16} aria-hidden="true" /> : null}
          </a>
        ))}
      </nav>
    );
  }
  return (
    <nav
      aria-label="Choose the period"
      data-block="stepper"
      className="inline-flex shrink-0 overflow-hidden rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)]"
    >
      {steps.map(({ link, words, way }, index) => (
        <Link key={`${index}-${words}`} href={resolve(link.href)} className={DESKTOP_STEP} rel={way === 'back' ? 'prev' : way === 'forward' ? 'next' : undefined}>
          {way === 'back' ? <ChevronLeft className="h-4 w-4" aria-hidden="true" /> : null}
          <span>{words}</span>
          {way === 'forward' ? <ChevronRight className="h-4 w-4" aria-hidden="true" /> : null}
        </Link>
      ))}
    </nav>
  );
}
