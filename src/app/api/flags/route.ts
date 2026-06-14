import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchFlags, backendRaiseFlag } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// CD → PL flag queue (GET) + raise a flag (POST). Backend enforces: only the CD
// raises; only the assigned PL acts.
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const user = await getCurrentUser();
  const status = new URL(req.url).searchParams.get("status") ?? undefined;
  const r = await fetchFlags({ email: user.email, role: user.role }, status);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}

export async function POST(req: Request) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await backendRaiseFlag({ email: user.email, role: user.role }, body);
  return r.live
    ? NextResponse.json({ live: true, flag: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: 502 });
}
