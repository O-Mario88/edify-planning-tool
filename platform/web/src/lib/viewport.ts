/**
 * Which reading a page gets: the phone's, drawn in the native app's design
 * (platform/mobile), or the desktop's, drawn in the existing web's. The line
 * is the existing web's own: below 64rem it shows its phone parts
 * (`desktop_hidden` in the feed reads lg classes at 64rem).
 *
 * The browser measures its screen and keeps the answer in a cookie
 * (shell/ViewportSync); until it has, the device's hints guess.
 */
export type View = 'phone' | 'desktop';

export const VIEW_COOKIE = 'edify_view';
/** The existing web's phone width: under its lg line. */
export const PHONE_QUERY = '(max-width: 63.999rem)';

const MOBILE_AGENT = /\b(iPhone|iPod|Android.*Mobile|Mobile Safari|Windows Phone)\b|Mobi\//i;

export interface ViewHints {
  /** The cookie the browser wrote, if any. */
  readonly cookie: string | undefined;
  /** Sec-CH-UA-Mobile: "?1" on a phone. */
  readonly mobileHint: string | null;
  readonly userAgent: string | null;
}

export function viewFrom({ cookie, mobileHint, userAgent }: ViewHints): View {
  if (cookie === 'phone' || cookie === 'desktop') return cookie;
  if (mobileHint === '?1') return 'phone';
  return userAgent && MOBILE_AGENT.test(userAgent) ? 'phone' : 'desktop';
}
