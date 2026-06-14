import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch, isBackendEnabled } from "@/lib/api/backend";

// Thin server-side proxy for the Budget Intelligence & Financial Decision
// Engine. The browser never sees the backend token — attached server-side and
// forwarded to edify-api, which re-enforces BUDGET_INTELLIGENCE_VIEW /
// BUDGET_DECISION_REVIEW. Covers refetch + review/note/recompute.
async function proxy(req: NextRequest, segments: string[], method: "GET" | "POST") {
  const user = await getCurrentUser();
  if (!isBackendEnabled()) {
    return NextResponse.json({ live: false, error: "Backend is not enabled." }, { status: 200 });
  }
  const sub = segments.join("/");
  const path = `/budget-intelligence/${sub}${req.nextUrl.search}`;
  const init: RequestInit = { method };
  if (method === "POST") {
    init.body = await req.text();
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await backendFetch<unknown>(path, { role: user.role, email: user.email }, init);
  return r.ok ? NextResponse.json(r.data) : NextResponse.json({ error: r.error }, { status: 502 });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  return proxy(req, path, "GET");
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  return proxy(req, path, "POST");
}
