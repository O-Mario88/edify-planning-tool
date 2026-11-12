import type { ReactNode } from 'react';

/** A surface card; `flush` for an edge-to-edge shell whose parts carry the 16px content line. */
export function Card({ children, flush = false, label }: { children: ReactNode; flush?: boolean; label?: string }) {
  return (
    <section
      aria-label={label}
      className={`rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-sm)] ${flush ? '' : 'p-4'}`}
    >
      {children}
    </section>
  );
}
