import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { environment } from '@/lib/environment';
import { isSameOrigin } from '@/lib/routes';
import { ACCESS_COOKIE } from '@/lib/session';

async function proxy(request: NextRequest, schoolId: string) {
  if (request.method !== 'GET' && !isSameOrigin(request)) {
    return NextResponse.json({ error: 'forbidden' }, { status: 403 });
  }
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: 'signed_out' }, { status: 401 });
  const base = environment().gatewayUrl.replace(/\/+$/, '');
  const target = `${base}/api/v1/schools/${encodeURIComponent(schoolId)}/gps-location`;

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
    return NextResponse.json(
      { error: 'Unable to reach Edify server. You can save this GPS reading offline as Pending Sync.' },
      { status: 503 },
    );
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ schoolId: string }> }) {
  const { schoolId } = await context.params;
  return proxy(request, schoolId);
}

export async function POST(request: NextRequest, context: { params: Promise<{ schoolId: string }> }) {
  const { schoolId } = await context.params;
  return proxy(request, schoolId);
}
