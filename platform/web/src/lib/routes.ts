/** Shared pieces of the /auth route handlers. */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import {
  ACCESS_COOKIE,
  CHALLENGE_COOKIE,
  REFRESH_COOKIE,
  accessCookie,
  isSecureOrigin,
  refreshCookie,
} from './session';

/**
 * A form post must come from this site's own pages (the cookies are
 * SameSite too; this refuses a cross-site post outright).
 */
export function isSameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get('origin');
  if (origin) return origin === request.nextUrl.origin;
  return request.headers.get('sec-fetch-site') === 'same-origin';
}

/** After a post, the browser GETs the next page. */
export function seeOther(request: NextRequest, path: string): NextResponse {
  return NextResponse.redirect(new URL(path, request.url), 303);
}

export function setSession(response: NextResponse, request: NextRequest, access: string, refresh?: string): void {
  const secure = isSecureOrigin(request.nextUrl);
  response.cookies.set(ACCESS_COOKIE, access, accessCookie(secure));
  if (refresh) response.cookies.set(REFRESH_COOKIE, refresh, refreshCookie(secure));
  response.cookies.delete({ name: CHALLENGE_COOKIE, path: '/auth' });
}

export function clearSession(response: NextResponse): void {
  response.cookies.delete({ name: ACCESS_COOKIE, path: '/' });
  response.cookies.delete({ name: REFRESH_COOKIE, path: '/auth' });
  response.cookies.delete({ name: CHALLENGE_COOKIE, path: '/auth' });
}

export async function formField(request: NextRequest, name: string, max = 512): Promise<string> {
  const form = await request.formData();
  const value = form.get(name);
  return typeof value === 'string' ? value.slice(0, max) : '';
}

export async function formFields(request: NextRequest, names: readonly string[], max = 512): Promise<Record<string, string>> {
  const form = await request.formData();
  return Object.fromEntries(
    names.map((name) => {
      const value = form.get(name);
      return [name, typeof value === 'string' ? value.slice(0, max) : ''];
    }),
  );
}
