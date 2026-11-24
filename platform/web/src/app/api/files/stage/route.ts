import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

import { environment } from '@/lib/environment';
import { ACCESS_COOKIE } from '@/lib/session';

/** The gateway's staging endpoint: a drawer's chosen file, checked and kept until its save. */
const STAGE_PATH = '/api/v1/files/stage';

export async function POST(request: Request) {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: 'Sign in first.' }, { status: 401 });
  }
  const contentType = request.headers.get('content-type') || '';
  if (!contentType.startsWith('multipart/form-data')) {
    return NextResponse.json({ error: 'A file is required.' }, { status: 400 });
  }
  const res = await fetch(`${environment().gatewayUrl}${STAGE_PATH}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': contentType },
    body: await request.arrayBuffer(),
    cache: 'no-store',
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json', 'Cache-Control': 'no-store' },
  });
}
