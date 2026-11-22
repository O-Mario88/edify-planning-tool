import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

import { environment } from '@/lib/environment';
import { ACCESS_COOKIE } from '@/lib/session';

export const dynamic = 'force-dynamic';

/**
 * Authenticated Server-Sent Events (SSE) proxy to the Go gateway's
 * role- and country-scoped realtime broker (/api/v1/realtime/stream).
 */
export async function GET(request: Request) {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: 'Sign in first.' }, { status: 401 });
  }
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: 'text/event-stream',
  };
  const lastEventId = request.headers.get('last-event-id');
  if (lastEventId) headers['Last-Event-ID'] = lastEventId;

  const upstream = await fetch(`${environment().gatewayUrl}/api/v1/realtime/stream`, {
    headers,
    cache: 'no-store',
    signal: request.signal,
  });

  if (!upstream.ok || !upstream.body) {
    return new NextResponse('Realtime stream unavailable', { status: upstream.status || 502 });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
