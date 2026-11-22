import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

import { environment } from '@/lib/environment';
import { ACCESS_COOKIE } from '@/lib/session';

const UPLOAD_ENDPOINTS: Record<string, { template: string; importPath: string; filename: string }> = {
  ssa: {
    template: '/api/v1/uploads/ssa/template',
    importPath: '/api/v1/uploads/ssa/import',
    filename: 'edify-ssa-upload-template.csv',
  },
  'planned-activities': {
    template: '/api/v1/uploads/planned-activities/template',
    importPath: '/api/v1/uploads/planned-activities/import',
    filename: 'edify-planned-activities-template.csv',
  },
};

export async function GET(_request: Request, context: { params: Promise<{ kind: string }> }) {
  const { kind } = await context.params;
  const spec = UPLOAD_ENDPOINTS[kind];
  if (!spec) {
    return NextResponse.json({ error: 'Unsupported upload template kind.' }, { status: 400 });
  }
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: 'Sign in first.' }, { status: 401 });
  }
  const res = await fetch(`${environment().gatewayUrl}${spec.template}`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  if (!res.ok) {
    const body = await res.text();
    return new NextResponse(body || 'Could not download template.', { status: res.status });
  }
  const data = await res.arrayBuffer();
  return new NextResponse(data, {
    status: 200,
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="${spec.filename}"`,
      'Cache-Control': 'no-store',
    },
  });
}

export async function POST(request: Request, context: { params: Promise<{ kind: string }> }) {
  const { kind } = await context.params;
  const spec = UPLOAD_ENDPOINTS[kind];
  if (!spec) {
    return NextResponse.json({ error: 'Unsupported upload import kind.' }, { status: 400 });
  }
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: 'Sign in first.' }, { status: 401 });
  }
  const contentType = request.headers.get('content-type') || 'text/csv';
  const body = await request.arrayBuffer();
  const res = await fetch(`${environment().gatewayUrl}${spec.importPath}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': contentType,
    },
    body,
    cache: 'no-store',
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': res.headers.get('Content-Type') || 'application/json' },
  });
}
