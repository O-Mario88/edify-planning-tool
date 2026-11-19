'use client';

/*
 * The app's "More" dropdown (mobile/src/ui/Dropdown.tsx): a button that
 * opens a panel under it, aligned to its end; a tap outside or Escape closes
 * it. It always drops down (owner, Dropdowns always drop down).
 */
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export interface MorePanelProps {
  /** What a screen reader hears for the button. */
  readonly label: string;
  /** The button's words ("More", "More 2"). */
  readonly words: ReactNode;
  /** The button is a segment of a rail, or a field-row button. */
  readonly look: 'seg' | 'more-button';
  /** A panel of fields (More filters) rather than a menu of links. */
  readonly roomy?: boolean;
  readonly children: ReactNode;
}

export function MorePanel({ label, words, look, roomy = false, children }: MorePanelProps) {
  const [isOpen, setOpen] = useState(false);
  const holder = useRef<HTMLDivElement>(null);
  const panelId = useId();
  useEffect(() => {
    if (!isOpen) return undefined;
    const away = (event: PointerEvent) => {
      if (!holder.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', escape);
    };
  }, [isOpen]);
  const Chevron = isOpen ? ChevronUp : ChevronDown;
  return (
    <div data-ph="more" ref={holder}>
      <button
        type="button"
        data-ph={look}
        aria-label={label}
        aria-expanded={isOpen}
        aria-controls={panelId}
        onClick={() => setOpen((open) => !open)}
      >
        {words}
        <Chevron size={14} aria-hidden="true" />
      </button>
      <div id={panelId} data-ph="more-panel" data-roomy={roomy || undefined} hidden={!isOpen} role={roomy ? 'group' : 'menu'} aria-label={label}>
        {children}
      </div>
    </div>
  );
}
