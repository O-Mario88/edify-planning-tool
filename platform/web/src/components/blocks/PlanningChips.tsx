import type { PageBadge } from '@/gen/edify/screens/v1/page_pb';

import { BadgeIcon } from '../shell/icons';

/**
 * A school's plan-status and Visit Lock chips (PageCell.pills), drawn as the
 * existing web draws `.school-planning-badge[data-planning-tone]`
 * (static/css/components.css): red Not Planned, orange planned, blue
 * awaiting verification, green complete, amber needs replanning, a grey held
 * visit with a shut padlock and an outlined unlocked one with an open padlock.
 */
const CHIP = 'border-[var(--edify-border)] bg-[var(--edify-surface-muted)] text-[var(--edify-text-muted)]';
const TONES: Readonly<Record<string, string>> = {
  none: 'border-[var(--edify-danger-border)] bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)]',
  planned: 'border-[#f59e0b] bg-[#fbbf24] text-[#78350f]',
  awaiting: 'border-[var(--edify-info-border)] bg-[var(--edify-info-light)] text-[var(--edify-info-text)]',
  verified: 'border-[var(--edify-success-border)] bg-[var(--edify-success-light)] text-[var(--edify-success-text)]',
  replan: 'border-[var(--edify-warning-border)] bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)]',
  open: 'border-[var(--edify-border)] bg-transparent text-[var(--edify-text-muted)]',
  closed: CHIP,
};

export function planningChipClasses(tone: string): string {
  return TONES[tone] ?? CHIP;
}

export function PlanningChips({ pills }: { pills: readonly PageBadge[] }) {
  return (
    <span className="inline-flex max-w-full flex-wrap gap-1">
      {pills.map((pill, index) => (
        <span
          key={index}
          title={pill.title || undefined}
          data-planning-tone={pill.tone}
          className={`inline-flex items-center whitespace-nowrap rounded-full border px-[0.35rem] text-[length:var(--edify-text-micro-size)] font-[number:var(--edify-text-micro-weight)] leading-[1.35] ${planningChipClasses(pill.tone)}`}
        >
          {pill.icon ? <BadgeIcon name={pill.icon} className="mr-[0.2rem] inline-block" /> : null}
          {pill.text}
          {pill.title && pill.icon === 'lock' ? <span className="sr-only">: {pill.title}</span> : null}
        </span>
      ))}
    </span>
  );
}
