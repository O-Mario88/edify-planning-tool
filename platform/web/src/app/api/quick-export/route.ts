import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { accessToken } from '@/lib/auth';
import { environment } from '@/lib/environment';

export async function GET(request: NextRequest) {
  const token = await accessToken().catch(() => '');
  if (!token) {
    return NextResponse.json({ error: 'Authentication required' }, { status: 401 });
  }
  const targetUrl = new URL('/api/v1/quick-export', environment().gatewayUrl);
  request.nextUrl.searchParams.forEach((v, k) => targetUrl.searchParams.set(k, v));

  const res = await fetch(targetUrl.toString(), {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });

  const body = await res.arrayBuffer();
  return new NextResponse(body, {
    status: res.status,
    headers: {
      'Content-Type': res.headers.get('Content-Type') || 'text/csv; charset=utf-8',
      'Content-Disposition': res.headers.get('Content-Disposition') || 'attachment; filename="edify-export.csv"',
      'Cache-Control': 'no-store',
    },
  });
}
