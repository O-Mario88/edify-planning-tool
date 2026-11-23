/* The pieces every drawer form draws the same way: its control style and its notes. */
import type { ReactNode } from 'react';

export const CONTROL =
  'w-full rounded-[var(--radius-control)] border border-[var(--edify-border-strong)] bg-[var(--edify-surface-raised)] px-3 py-2 text-[length:var(--edify-text-body-size)] text-[var(--edify-text)] outline-none focus:border-[var(--edify-accent)] focus:ring-2 focus:ring-[var(--edify-accent-soft,transparent)] disabled:opacity-60';

const NOTE_TONES: Readonly<Record<string, string>> = {
  danger: 'border-[var(--edify-danger-border,var(--edify-border))] bg-[var(--edify-danger-soft,var(--edify-surface-muted))] text-[var(--edify-danger-text,var(--edify-text))]',
  warning: 'border-[var(--edify-warning-border,var(--edify-border))] bg-[var(--edify-warning-soft,var(--edify-surface-muted))] text-[var(--edify-warning-text,var(--edify-text))]',
  success: 'border-[var(--edify-success-border,var(--edify-border))] bg-[var(--edify-success-soft,var(--edify-surface-muted))] text-[var(--edify-success-text,var(--edify-text))]',
  info: 'border-[var(--edify-border)] bg-[var(--edify-surface-muted)] text-[var(--edify-text)]',
};

interface NoteProps {
  readonly tone?: string;
  readonly title?: string;
  readonly text: string;
  readonly children?: ReactNode;
}

export function Note({ tone = 'info', title, text, children }: NoteProps) {
  return (
    <div role={tone === 'danger' ? 'alert' : undefined} className={`space-y-1.5 rounded-[var(--radius-control)] border px-3 py-2 text-[length:var(--edify-text-label-size)] ${NOTE_TONES[tone] ?? NOTE_TONES.info}`}>
      {title ? <p className="font-bold">{title}</p> : null}
      {text ? <p>{text}</p> : null}
      {children}
    </div>
  );
}
