import type { ReactNode } from 'react';

/** A surface card, as the existing web's .card; `flush` for an edge-to-edge shell whose parts carry the 16px content line. */
export function Card({ children, flush = false, label }: { children: ReactNode; flush?: boolean; label?: string }) {
  return (
    <section aria-label={label} className={flush ? 'card p-0 overflow-hidden' : 'card p-4'}>
      {children}
    </section>
  );
}
