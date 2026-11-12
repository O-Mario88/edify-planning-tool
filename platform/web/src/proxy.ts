/**
 * Every page but sign-in needs a session: without an access cookie the
 * reader goes to /auth/refresh (which renews it from the refresh cookie, or
 * ends at /login). The path is passed on so a page can send the reader back.
 */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { ACCESS_COOKIE } from './lib/session';

const PUBLIC = [/^\/login$/, /^\/auth\//, /^\/_next\//, /^\/favicon/];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (PUBLIC.some((pattern) => pattern.test(pathname))) return NextResponse.next();
  const path = pathname + search;
  if (!request.cookies.get(ACCESS_COOKIE)?.value) {
    const target = new URL('/auth/refresh', request.url);
    target.searchParams.set('next', path);
    return NextResponse.redirect(target);
  }
  const forwarded = new Headers(request.headers);
  forwarded.set('x-edify-path', path);
  return NextResponse.next({ request: { headers: forwarded } });
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] };
