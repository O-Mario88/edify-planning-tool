import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

import { environment } from '@/lib/environment';
import { ACCESS_COOKIE } from '@/lib/session';

const ALLOWED_KINDS = new Set([
  'school_directory',
  'core_schools',
  'clusters',
  'cluster_schools',
  'completed_visits',
  'finance_weekly',
  'ssa_records',
  'escalations',
  'leave_requests',
  'debriefs',
  'decision_log',
]);

const ALLOWED_FILTER_KEYS = new Set(['fy', 'district', 'school_type', 'status', 'q', 'cluster_id']);

/**
 * Streams a native Go CSV export directly to the browser without calling Django,
 * preserving authorized query filters (FY, district, type, search, cluster).
 */
export async function GET(request: Request, context: { params: Promise<{ kind: string }> }) {
  const { kind } = await context.params;
  if (!ALLOWED_KINDS.has(kind)) {
    return NextResponse.json({ error: 'Unsupported export kind.' }, { status: 400 });
  }
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: 'Sign in first.' }, { status: 401 });
  }
  const url = new URL(request.url);
  const filters: Record<string, string> = {};
  for (const [k, v] of url.searchParams.entries()) {
    if (ALLOWED_FILTER_KEYS.has(k.toLowerCase()) && v.trim()) {
      filters[k.toLowerCase()] = v.trim();
    }
  }

  const gatewayUrl = environment().gatewayUrl;
  const createRes = await fetch(`${gatewayUrl}/api/v1/exports`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ kind, filters }),
    cache: 'no-store',
  });
  if (!createRes.ok) {
    const body = await createRes.text();
    return new NextResponse(body || 'Could not generate export.', {
      status: createRes.status,
      headers: { 'Content-Type': createRes.headers.get('Content-Type') ?? 'application/json' },
    });
  }
  const created = (await createRes.json()) as { id: string; filename?: string; download_url?: string };
  const downloadPath = created.download_url || `/api/v1/exports/${created.id}/download`;
  const downloadRes = await fetch(`${gatewayUrl}${downloadPath}`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  if (!downloadRes.ok) {
    const body = await downloadRes.text();
    return new NextResponse(body || 'Could not download export.', { status: downloadRes.status });
  }
  const csv = await downloadRes.arrayBuffer();
  const filename = created.filename || `${kind}.csv`;
  return new NextResponse(csv, {
    status: 200,
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="${filename}"`,
      'Cache-Control': 'no-store',
    },
  });
}
