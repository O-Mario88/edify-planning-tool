'use client';

/*
 * A record's one Actions menu (owner, 2026-09-26): it opens at its button and
 * drops down (owner, 2026-09-27). An action the record cannot take stays on
 * the list, greyed, with its reason under it.
 */
import { useEffect, useRef, useState } from 'react';

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
  // The existing row menu (templates/components/row_actions.html).
  return (
    <div className="row-menu" data-row-actions="" ref={ref}>
      <button type="button" className="row-menu__trigger" aria-haspopup="menu" aria-expanded={open} aria-label={`Actions for ${subject}`} onClick={() => setOpen(!open)}>
        Actions
        <svg className={`row-menu__caret ${open ? 'is-open' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open ? (
        <div className="row-menu__list" role="menu">
          {actions.map((action) =>
            action.enabled && action.onSelect ? (
              <button
                key={action.key}
                type="button"
                role="menuitem"
                className="row-menu__item"
                onClick={() => {
                  setOpen(false);
                  action.onSelect?.();
                }}
              >
                {action.label}
              </button>
            ) : action.enabled ? (
              <a key={action.key} role="menuitem" href={action.href} className="row-menu__item">
                {action.label}
              </a>
            ) : (
              <button key={action.key} type="button" role="menuitem" aria-disabled="true" className="row-menu__item">
                {action.label}
                {action.reason ? <span className="row-menu__reason">{action.reason}</span> : null}
              </button>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}
