import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

import { environment } from '@/lib/environment';
import { ACCESS_COOKIE } from '@/lib/session';

const ALLOWED_SECTIONS = new Set([
  'command',
  'my',
  'meetings',
  'training',
  'attendance',
  'schools',
  'ssa',
  'teachers',
  'leaders',
  'students',
  'academic',
  'loans',
  'stories',
  'impact',
  'planning',
  'evidence',
]);

/**
 * Streams a native Go Cluster Oversight section CSV directly to the browser
 * without calling Django.
 */
export async function GET(request: Request, context: { params: Promise<{ section: string }> }) {
  const { section } = await context.params;
  if (!ALLOWED_SECTIONS.has(section)) {
    return NextResponse.json({ error: 'Unknown Cluster Oversight section.' }, { status: 404 });
  }
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: 'Sign in first.' }, { status: 401 });
  }
  const incoming = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of ['fy', 'area', 'view']) {
    const val = incoming.get(key);
    if (val) query.set(key, val);
  }
  const qs = query.toString();
  const gatewayUrl = environment().gatewayUrl;
  const res = await fetch(`${gatewayUrl}/api/v1/cluster-oversight/${section}/csv${qs ? `?${qs}` : ''}`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  if (!res.ok) {
    const body = await res.text();
    return new NextResponse(body || 'Could not export Cluster Oversight section.', {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('Content-Type') ?? 'text/plain; charset=utf-8' },
    });
  }
  const csv = await res.arrayBuffer();
  const disposition = res.headers.get('Content-Disposition') || `attachment; filename="cluster-oversight-${section}.csv"`;
  return new NextResponse(csv, {
    status: 200,
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': disposition,
      'Cache-Control': 'no-store',
    },
  });
}
