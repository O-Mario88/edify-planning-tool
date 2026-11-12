/**
 * The session cookies. Tokens live only in httpOnly cookies the Next.js
 * server sets (src/app/auth/*), never in browser storage, so page script
 * cannot read them.
 */
export const ACCESS_COOKIE = 'edify_at';
export const REFRESH_COOKIE = 'edify_rt';
/** A sign-in stopped for a code: the challenge, for the code step only. */
export const CHALLENGE_COOKIE = 'edify_challenge';

/** Access tokens are short-lived; the gateway decides, this only tidies. */
const ACCESS_MAX_AGE_SECONDS = 15 * 60;
const REFRESH_MAX_AGE_SECONDS = 14 * 24 * 60 * 60;
const CHALLENGE_MAX_AGE_SECONDS = 10 * 60;

export interface CookieOptions {
  readonly httpOnly: true;
  readonly sameSite: 'lax' | 'strict';
  readonly secure: boolean;
  readonly path: string;
  readonly maxAge: number;
}

/** Plain http is allowed only on this machine (development). */
export function isSecureOrigin(url: URL): boolean {
  return url.protocol === 'https:';
}

export function accessCookie(secure: boolean): CookieOptions {
  return { httpOnly: true, sameSite: 'lax', secure, path: '/', maxAge: ACCESS_MAX_AGE_SECONDS };
}

/** The refresh token is sent only to the routes that renew or end a session. */
export function refreshCookie(secure: boolean): CookieOptions {
  return { httpOnly: true, sameSite: 'strict', secure, path: '/auth', maxAge: REFRESH_MAX_AGE_SECONDS };
}

export function challengeCookie(secure: boolean): CookieOptions {
  return { httpOnly: true, sameSite: 'strict', secure, path: '/auth', maxAge: CHALLENGE_MAX_AGE_SECONDS };
}

/**
 * Where to go after signing in: a path on this site, never another origin
 * ("//evil", "https://…", "/\\evil" are refused).
 */
export function safeNext(raw: string | null | undefined, fallback = '/schools'): string {
  const value = (raw ?? '').trim();
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\') || value.includes('\n')) {
    return fallback;
  }
  if (value.startsWith('/auth/') || value === '/login') return fallback;
  return value;
}
