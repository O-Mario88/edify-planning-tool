import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchFundRequests, submitFundRequest } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// Fund-request queue (GET, role-scoped) + submit/generate a request (POST). No mock.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchFundRequests(user);
  return r.live
    ? NextResponse.json({ live: true, requests: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}

export async function POST(req: Request) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await submitFundRequest(
    { email: user.email, role: user.role },
    { period: body.period ?? "monthly", month: body.month, quarter: body.quarter },
  );
  return r.live
    ? NextResponse.json({ live: true, request: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: 502 });
}
