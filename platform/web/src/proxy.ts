/**
 * Every page but sign-in needs a session: without an access cookie the
 * reader goes to /auth/refresh (which renews it from the refresh cookie, or
 * ends at /login). The path is passed on so a page can send the reader back.
 * A request other than a GET without one (a save) is answered 401 instead.
 */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { ACCESS_COOKIE } from './lib/session';

const PUBLIC = [/^\/login$/, /^\/auth\//, /^\/_next\//, /^\/favicon/, /^\/static\//];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (PUBLIC.some((pattern) => pattern.test(pathname))) return NextResponse.next();
  const path = pathname + search;
  if (!request.cookies.get(ACCESS_COOKIE)?.value) {
    // A save or other POST cannot follow a redirect to /auth/refresh (a GET):
    // it is told it is signed out, and the page renews the session and
    // tries again.
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return NextResponse.json({ error: 'signed_out' }, { status: 401 });
    }
    const target = new URL('/auth/refresh', request.url);
    target.searchParams.set('next', path);
    return NextResponse.redirect(target);
  }
  const forwarded = new Headers(request.headers);
  forwarded.set('x-edify-path', path);
  if (request.method === 'GET' && /^\/cluster-oversight\/directory\/?$/.test(pathname)) {
    return NextResponse.redirect(new URL('/clusters', request.url));
  }
  if (request.method === 'GET' && request.nextUrl.searchParams.get('format') === 'csv') {
    const csvMatch = pathname.match(/^\/cluster-oversight\/([a-z]+)\/?$/);
    if (csvMatch?.[1]) {
      const target = new URL(`/exports/cluster-oversight/${csvMatch[1]}${search}`, request.url);
      return NextResponse.rewrite(target, { request: { headers: forwarded } });
    }
  }
  // A page's own Export (?export=xlsx) whose workbook the gateway makes.
  const params = request.nextUrl.searchParams;
  // My Plan's Export (_export_format): export=csv|xlsx|excel, format=xlsx|excel,
  // or the Export options drawer's period fields.
  const myPlanExport =
    /^\/my-plan\/?$/.test(pathname) &&
    (['csv', 'xlsx', 'excel'].includes((params.get('export') ?? '').trim().toLowerCase()) ||
      ['xlsx', 'excel'].includes((params.get('format') ?? '').trim().toLowerCase()) ||
      ['from_month', 'to_month', 'start_date', 'end_date', 'period_type'].some((key) => params.has(key)));
  const exportsPage =
    request.method === 'GET' &&
    (myPlanExport ||
      (Boolean(params.get('export')?.trim()) &&
      /^\/ia\/(returned|partner-evidence|history|verification)\/?$/.test(pathname)) ||
      (/^\/core-schools-oversight\/?$/.test(pathname) &&
        (params.get('format') === 'csv' ||
          (params.get('format') === 'xlsx' && /^core_(visits|trainings)$/.test(params.get('tab') ?? '')))));
  if (
    exportsPage ||
    (request.method === 'GET' &&
      /^\/(ia\/analytics\/export|ia\/impact-reports\/[^/]+\/annex\.csv|ia\/impact-reports\/[^/]+\/releases\/[^/]+\/download|my-professional-development\/export|my-targets\/export|projects\/export|projects\/[^/]+\/export|staff-activity\/export|schools\/upload\/template|clusters\/[^/]+\/schools\/export|country-planning-oversight\/table-export\/(?!all\/?$)[a-z-]+|team-planning-oversight\/export|country-planning-oversight\/export|country-planning-oversight\/coverage-export)\/?$/.test(
        pathname,
      ))
  ) {
    const clean = pathname.replace(/\/$/, '');
    const target = new URL('/api/quick-export', request.url);
    target.searchParams.set('target', clean);
    request.nextUrl.searchParams.forEach((v, k) => target.searchParams.set(k, v));
    return NextResponse.rewrite(target, { request: { headers: forwarded } });
  }
  return NextResponse.next({ request: { headers: forwarded } });
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] };
