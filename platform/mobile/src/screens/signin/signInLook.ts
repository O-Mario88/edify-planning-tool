/**
 * The web sign-in page's measurements (owner, 2026-11-11: the app's sign-in
 * is an exact replica of the web's on phone, tablet and desktop). Every value
 * here was read from the rendered web page (templates/layouts/login.html with
 * static/css/login.css) at 1440, 768 and 390 px wide, not from the stylesheet
 * alone, because several later rules there override earlier ones.
 */

/** Above this width the page splits: the photo panel left, the form right (70rem). */
export const SPLIT_ABOVE = 1120;
/** At or below this width the phone rules apply (40rem). */
export const PHONE_AT_MOST = 640;
/** The brand panel's figures turn 2 x 2 when its content is this narrow (40rem). */
export const BRAND_GRID_BELOW = 640;
/** A split page this short tightens its brand panel (54rem). */
export const SHORT_AT_MOST = 864;

const clamp = (low: number, value: number, high: number) => Math.min(high, Math.max(low, value));

/** The web's fluid type sizes, for a window width in px. */
export function typeSizes(width: number) {
  return {
    /** --edify-text-label-size: clamp(.8125rem, .798rem + .064vw, .875rem) */
    label: clamp(13, 12.768 + 0.00064 * width, 14),
    /** --edify-text-micro-size: clamp(.75rem, .736rem + .064vw, .8125rem) */
    micro: clamp(12, 11.776 + 0.00064 * width, 13),
    /** --edify-text-display-size: clamp(1.25rem, 1.163rem + .385vw, 1.625rem) */
    display: clamp(20, 18.608 + 0.00385 * width, 26),
    /** .login-brand__title: clamp(3rem, 4vw, 4.05rem) */
    brandTitle: clamp(48, 0.04 * width, 64.8),
  };
}

/** How the page is laid out at a window size. */
export function signInLayout(width: number, height: number) {
  const isSplit = width > SPLIT_ABOVE;
  const isPhone = width <= PHONE_AT_MOST;
  // .login-shell: grid-template-columns: minmax(0, 1.15fr) minmax(35rem, 1fr)
  const accessWidth = isSplit ? Math.max(560, width / 2.15) : width;
  const brandWidth = isSplit ? width - accessWidth : 0;
  return {
    isSplit,
    isPhone,
    isShort: isSplit && height <= SHORT_AT_MOST,
    brandWidth,
    accessWidth,
    /** The brand panel's content width (its padding is 48 each side). */
    brandContentWidth: Math.max(0, brandWidth - 96),
    /** .login-card: min(100%, 29rem) */
    cardWidth: isSplit ? Math.min(accessWidth - 2 * clamp(24, 0.03 * width, 48), 464) : Math.min(width - 32, 464),
    /** .login-card__inner side padding */
    innerSide: isSplit ? clamp(24, 0.03 * width, 44) : clamp(24, 0.05 * width, 44),
    innerVertical: isSplit ? (height <= 704 ? 28 : 44) : 40,
    /** The coloured line along the top of the card, single column only. */
    barHeight: isSplit ? 0 : isPhone ? 3.2 : 4,
  };
}

export const ink = {
  title: '#17232b',
  label: '#233844',
  muted: '#5b708a',
  field: '#f8fafb',
  fieldBorder: '#c7d1d7',
  focus: '#1872bd',
  toggle: '#0d5b9e',
  forgot: '#2779c2',
  cardBorder: '#d9e3ed',
  rule: '#e3eaf1',
  shield: '#0865ad',
  page: '#e7f4fc',
  danger: '#be123c',
  success: '#087b63',
  info: '#0d5b9e',
};

export const gradients = {
  submit: 'linear-gradient(105deg, #075397 0%, #105fa6 100%)',
  bar: 'linear-gradient(90deg, #0a4d86, #2494d0 52%, #75cdf3)',
  panel: 'linear-gradient(110deg, #073454, #103f62)',
  access:
    'radial-gradient(circle at 9% 55%, rgba(126, 205, 246, 0.34), transparent 41%), radial-gradient(circle at 92% 5%, rgba(235, 249, 255, 0.92), transparent 38%), linear-gradient(135deg, #dff1fb 0%, #eef9fe 48%, #dceefa 100%)',
  shadeDown: 'linear-gradient(180deg, rgba(0, 22, 43, 0.55) 0%, rgba(0, 38, 73, 0.52) 36%, rgba(0, 36, 69, 0.82) 72%, rgba(0, 25, 49, 0.98) 100%)',
  shadeAcross: 'linear-gradient(90deg, rgba(0, 28, 54, 0.45) 0%, rgba(0, 52, 93, 0.34) 100%)',
};

export const shadows = {
  card: '0px 16px 48px 0px rgba(7, 38, 65, 0.09)',
  submit: '0px 10px 20px 0px rgba(8, 76, 137, 0.18)',
  shieldTile: '0px 7px 16px 0px rgba(20, 71, 109, 0.12)',
  impact: '0px 18px 42px 0px rgba(0, 19, 39, 0.16)',
  figures: '0px 3px 12px 0px rgba(15, 23, 42, 0.06)',
};

export const panel = {
  border: '#38607d',
  divider: '#38556f',
  impactDivider: 'rgba(131, 196, 234, 0.2)',
  label: '#d4e7fa',
};
