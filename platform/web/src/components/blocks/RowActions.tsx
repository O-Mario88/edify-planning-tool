'use client';

/*
 * A record's one Actions menu (owner, 2026-09-26): it opens at its button and
 * drops down (owner, 2026-09-27). An action the record cannot take stays on
 * the list, greyed, with its reason under it.
 */
import { useEffect, useRef, useState } from 'react';

import { Icon } from '../shell/icons';

export interface RowAction {
  readonly key: string;
  readonly label: string;
  readonly enabled: boolean;
  readonly reason: string;
  readonly href: string;
  /** Runs on the page instead of opening href (a revocation asks its reason in place). */
  readonly onSelect?: () => void;
}

export function RowActions({ subject, actions }: { subject: string; actions: readonly RowAction[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => ref.current && !ref.current.contains(event.target as Node) && setOpen(false);
    const escape = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);
  if (!actions.length) return null;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Actions for ${subject}`}
        onClick={() => setOpen(!open)}
        className="inline-flex h-6 items-center gap-1 rounded-[var(--radius-control)] border border-[var(--brand-primary-border)] bg-[var(--edify-surface)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--brand-primary-text)] dark:text-[var(--edify-accent-text)]"
      >
        Actions
        <Icon name="chevronDown" className="h-3.5 w-3.5" />
      </button>
      {open ? (
        <div role="menu" className="absolute right-0 top-full z-40 mt-1 min-w-52 rounded-[var(--radius-surface)] border border-[var(--edify-border)] bg-[var(--edify-surface)] py-1 shadow-lg">
          {actions.map((action) =>
            action.enabled && action.onSelect ? (
              <button
                key={action.key}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  action.onSelect?.();
                }}
                className="block w-full px-4 py-2 text-left text-[13px] font-semibold text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)]"
              >
                {action.label}
              </button>
            ) : action.enabled ? (
              <a key={action.key} role="menuitem" href={action.href} className="block px-4 py-2 text-[13px] font-semibold text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)]">
                {action.label}
              </a>
            ) : (
              <span key={action.key} role="menuitem" aria-disabled="true" className="block cursor-not-allowed px-4 py-2 text-[13px] font-semibold text-[var(--edify-text-subtle)]">
                {action.label}
                {action.reason ? <span className="block text-[12px] font-medium">{action.reason}</span> : null}
              </span>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}
