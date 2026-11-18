import { toJson } from '@bufbuild/protobuf';
import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { GetPageResponseSchema, PageScreenService } from '@/gen/edify/screens/v1/page_screen_pb';
import { gatewayClient, isNotFound, isUnauthenticated, isUnavailable } from '@/lib/gateway';
import { isPagePart } from '@/lib/pagePart';
import { ACCESS_COOKIE } from '@/lib/session';

/**
 * A part of a page that loads once something opens (a cluster card's
 * schools), asked of the gateway as the reader and answered as the page
 * contract's JSON. Only the allow-listed parts are asked; reads only.
 */
export async function GET(request: NextRequest) {
  const path = request.nextUrl.searchParams.get('path') ?? '';
  if (!isPagePart(path)) return NextResponse.json({ error: 'not_found' }, { status: 404 });
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: 'signed_out' }, { status: 401 });
  try {
    const answer = await gatewayClient(PageScreenService, token).getPage({ path, query: {}, desktop: true });
    return NextResponse.json(toJson(GetPageResponseSchema, answer), { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    if (isUnauthenticated(error)) return NextResponse.json({ error: 'signed_out' }, { status: 401 });
    if (isNotFound(error)) return NextResponse.json({ error: 'not_found' }, { status: 404 });
    if (isUnavailable(error)) return NextResponse.json({ error: 'not_moved' }, { status: 503 });
    throw error;
  }
}
