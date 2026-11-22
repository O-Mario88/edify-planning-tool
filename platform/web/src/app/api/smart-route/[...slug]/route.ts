import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { environment } from '@/lib/environment';
import { isSameOrigin } from '@/lib/routes';
import { ACCESS_COOKIE } from '@/lib/session';

const ALLOWED_SMART_ROUTE = new Set(['day', 'optimize', 'directions', 'save', 'validate', 'road-conditions']);

function upstreamUrl(slug: string[], search: string): string | null {
  if (!slug || slug.length === 0) return null;
  const base = environment().gatewayUrl.replace(/\/+$/, '');
  if (slug[0] === 'scheduling' && slug[1] === 'calendar-rules') {
    return `${base}/api/v1/scheduling/calendar-rules${search}`;
  }
  if (!ALLOWED_SMART_ROUTE.has(slug[0]!)) return null;
  return `${base}/api/v1/smart-route/${slug.map(encodeURIComponent).join('/')}${search}`;
}

async function forward(request: NextRequest, slug: string[]) {
  if (request.method !== 'GET' && !isSameOrigin(request)) {
    return NextResponse.json({ error: 'forbidden' }, { status: 403 });
  }
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: 'signed_out' }, { status: 401 });
  const target = upstreamUrl(slug, request.nextUrl.search);
  if (!target) return NextResponse.json({ error: 'not_found' }, { status: 404 });

  const init: RequestInit = {
    method: request.method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(request.method !== 'GET' ? { 'Content-Type': 'application/json' } : {}),
    },
    cache: 'no-store',
  };
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = await request.text();
  }
  try {
    const res = await fetch(target, init);
    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: {
        'Content-Type': res.headers.get('content-type') || 'application/json',
        'Cache-Control': 'no-store',
      },
    });
  } catch {
    return NextResponse.json({ error: 'Smart Route service temporarily unreachable' }, { status: 502 });
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ slug: string[] }> }) {
  const { slug } = await context.params;
  return forward(request, slug);
}

export async function POST(request: NextRequest, context: { params: Promise<{ slug: string[] }> }) {
  const { slug } = await context.params;
  return forward(request, slug);
}
