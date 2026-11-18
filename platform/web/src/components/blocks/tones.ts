/**
 * Tones arrive as data (`danger`, `warning`, `success`, `info`, `neutral`,
 * `positive`, `attention`); these are the classes the existing web draws
 * each with (its .edify-badge[data-tone] and is-* rules).
 */
const BASE_BADGE = {
  danger: 'border-[#fecdd3] bg-[#fff1f2] text-[#be123c] dark:border-[rgba(241,143,138,0.35)] dark:bg-[var(--edify-danger-light)] dark:text-[var(--edify-danger)]',
  warning: 'border-[var(--edify-warning-border)] bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)]',
  success: 'border-[#a7f3d0] bg-[#ecfdf5] text-[#065f46] dark:border-[rgba(121,202,152,0.35)] dark:bg-[var(--edify-success-light)] dark:text-[var(--edify-success)]',
  info: 'border-[var(--brand-primary-border)] bg-[var(--brand-primary-soft)] text-[var(--brand-primary-text)]',
  neutral: 'border-[var(--edify-border)] bg-[var(--edify-surface-muted)] text-[var(--edify-text)]',
} as const;
/**
 * The page feed's own tone words (PageBadge / PageFact: good, caution, alert,
 * plain; PageCell badges: the existing web's colour names) drawn as the same
 * five.
 */
const BADGE: Readonly<Record<string, string>> = {
  ...BASE_BADGE,
  positive: BASE_BADGE.success,
  attention: BASE_BADGE.warning,
  good: BASE_BADGE.success,
  green: BASE_BADGE.success,
  lime: BASE_BADGE.success,
  caution: BASE_BADGE.warning,
  amber: BASE_BADGE.warning,
  alert: BASE_BADGE.danger,
  rose: BASE_BADGE.danger,
  blue: BASE_BADGE.info,
  primary: BASE_BADGE.info,
  purple: BASE_BADGE.info,
  plain: BASE_BADGE.neutral,
  slate: BASE_BADGE.neutral,
};

export function badgeClasses(tone: string): string {
  return BADGE[tone] ?? BASE_BADGE.neutral;
}

const TEXT: Readonly<Record<string, string>> = {
  danger: 'text-[#be123c] dark:text-[var(--edify-danger)]',
  warning: 'text-[var(--edify-warning-text)]',
  attention: 'text-[var(--edify-warning-text)]',
  success: 'text-[#047857] dark:text-[var(--edify-success)]',
  positive: 'text-[#047857] dark:text-[var(--edify-success)]',
  info: 'text-[var(--brand-primary-text)]',
  good: 'text-[#047857] dark:text-[var(--edify-success)]',
  lime: 'text-[#047857] dark:text-[var(--edify-success)]',
  caution: 'text-[var(--edify-warning-text)]',
  alert: 'text-[#be123c] dark:text-[var(--edify-danger)]',
};

export function textTone(tone: string): string {
  return TEXT[tone] ?? '';
}

/**
 * A record card's fact values (`.school-record-row__metadata dd`,
 * static/css/platform.css): plain values in the accent blue, the card's
 * danger, warning and success colours for its toned ones.
 */
const RECORD_FACT: Readonly<Record<string, string>> = {
  alert: 'text-[var(--edify-danger)]',
  danger: 'text-[var(--edify-danger)]',
  caution: 'text-[var(--edify-warning)]',
  warning: 'text-[var(--edify-warning)]',
  good: 'text-[var(--edify-success)]',
  success: 'text-[var(--edify-success)]',
};

export function recordFactTone(tone: string): string {
  return RECORD_FACT[tone] ?? (textTone(tone) || 'text-[var(--edify-accent-text)]');
}

/**
 * The existing web's own tone for a figure in a table
 * (`.edify-status-text[data-edify-tone=…]`): danger, warning, success, info
 * or neutral; empty for an untoned figure.
 */
const EDIFY_TONE: Readonly<Record<string, string>> = {
  danger: 'danger',
  alert: 'danger',
  rose: 'danger',
  warning: 'warning',
  caution: 'warning',
  attention: 'warning',
  amber: 'warning',
  success: 'success',
  positive: 'success',
  good: 'success',
  green: 'success',
  lime: 'success',
  info: 'info',
  primary: 'info',
  blue: 'info',
  neutral: 'neutral',
  plain: 'neutral',
  slate: 'neutral',
};

export function edifyTone(tone: string): string {
  return EDIFY_TONE[tone] ?? '';
}
