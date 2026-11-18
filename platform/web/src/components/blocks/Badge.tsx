import { BadgeIcon } from '../shell/icons';

/* The existing badge (templates/components/badge.html): its tone classes, by the badge tone words. */
const TONE_CLASS: Readonly<Record<string, string>> = {
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  danger: 'bg-rose-50 text-rose-700 border-rose-200',
  info: 'edify-primary-soft edify-primary-text edify-primary-border',
  purple: 'bg-violet-50 text-violet-700 border-violet-200',
};
const NEUTRAL = 'bg-slate-100 text-slate-700 border-slate-200';

/** The page feed's tone words, as the badge's five. */
const ALIAS: Readonly<Record<string, string>> = {
  positive: 'success',
  good: 'success',
  green: 'success',
  lime: 'success',
  attention: 'warning',
  caution: 'warning',
  amber: 'warning',
  alert: 'danger',
  rose: 'danger',
  blue: 'info',
  primary: 'info',
};

export function badgeTone(tone: string): string {
  const word = ALIAS[tone] ?? tone;
  return TONE_CLASS[word] ?? NEUTRAL;
}

export function Badge({ tone, children, title, icon = '' }: { tone: string; children: React.ReactNode; title?: string; icon?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 px-1.5 py-0.5 edify-text-caption font-semibold rounded-pill border whitespace-nowrap ${badgeTone(tone)}`}>
      {icon ? <BadgeIcon name={icon} /> : null}
      {children}
    </span>
  );
}
