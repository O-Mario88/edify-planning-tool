/** Header buttons: one filled primary, the rest outlined (owner, 2026-09-26). */
export const BUTTON_BASE =
  'inline-flex h-10 items-center gap-1.5 rounded-[var(--radius-control)] px-4 text-[length:var(--edify-text-label-size)] font-semibold whitespace-nowrap transition-colors';
export const BUTTON_PRIMARY = `${BUTTON_BASE} bg-[var(--edify-accent)] text-white shadow-sm hover:bg-[var(--brand-primary-hover)]`;
export const BUTTON_OUTLINE = `${BUTTON_BASE} border border-[var(--edify-border)] bg-[var(--edify-surface)] text-[var(--edify-text)] hover:bg-[var(--brand-primary-soft)]`;
