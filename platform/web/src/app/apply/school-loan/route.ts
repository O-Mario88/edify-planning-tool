import { NextResponse } from 'next/server';

import { environment } from '@/lib/environment';

/** Proxies the Go-rendered School Loan Application page (/loans/apply). */
export async function GET() {
  const url = new URL('/loans/apply', environment().gatewayUrl);
  const res = await fetch(url.toString(), { cache: 'no-store' });
  const html = await res.text();
  return new NextResponse(html, {
    status: res.status,
    headers: {
      'Content-Type': res.headers.get('Content-Type') || 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}
