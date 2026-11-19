/**
 * The tone a server word names, as the phone design colours it (the app's
 * shared.toneColor and theme.toneColors): good, alert, caution, info or
 * brand; anything else is plain.
 */
export type PhoneTone = 'good' | 'alert' | 'caution' | 'info' | 'brand';

const TONES: Readonly<Record<string, PhoneTone>> = {
  success: 'good',
  good: 'good',
  positive: 'good',
  green: 'good',
  danger: 'alert',
  alert: 'alert',
  negative: 'alert',
  red: 'alert',
  rose: 'alert',
  warning: 'caution',
  caution: 'caution',
  attention: 'caution',
  amber: 'caution',
  info: 'info',
  primary: 'info',
  lime: 'info',
  blue: 'info',
  brand: 'brand',
};

export function phoneTone(tone: string): PhoneTone | undefined {
  return TONES[tone];
}

/** Tiles a row: two on a phone; on a wide screen rows as even as they can be (at most five). */
export function tileColumns(count: number, isWide: boolean): number {
  if (!isWide) return Math.min(2, Math.max(count, 1));
  if (count <= 1) return 1;
  return Math.ceil(count / Math.ceil(count / 5));
}
