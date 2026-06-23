import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch, isBackendEnabled } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";

export const dynamic = "force-dynamic";

async function proxy(req: NextRequest, segments: string[], method: "GET" | "POST") {
  const user = await getCurrentUser();
  if (!isBackendEnabled()) {
    return NextResponse.json({ live: false, error: "Backend is not enabled." }, { status: 200 });
  }
  const sub = segments.join("/");
  const path = `/core/${sub}${req.nextUrl.search}`;
  const init: RequestInit = { method };
  if (method === "POST") {
    init.body = await req.text();
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await backendFetch<unknown>(path, { role: user.role, email: user.email }, init);
  return r.ok
    ? NextResponse.json({ live: true, data: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  return proxy(req, path, "GET");
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { path = [] } = await ctx.params;
  return proxy(req, path, "POST");
}
