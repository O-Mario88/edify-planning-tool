import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

import { environment } from '@/lib/environment';
import { ACCESS_COOKIE } from '@/lib/session';

/**
 * Downloads the official SSA Bulk Upload CSV template directly from the Go
 * gateway without calling Django.
 */
export async function GET() {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: 'Sign in first.' }, { status: 401 });
  }
  const res = await fetch(`${environment().gatewayUrl}/api/v1/uploads/ssa/template`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  if (!res.ok) {
    const body = await res.text();
    return new NextResponse(body || 'Could not download SSA template.', { status: res.status });
  }
  const csv = await res.arrayBuffer();
  return new NextResponse(csv, {
    status: 200,
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="edify-ssa-upload-template.csv"',
      'Cache-Control': 'no-store',
    },
  });
}
