import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { submitDebrief, fetchDebriefsToday, type SubmitDebriefBody } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// Daily Debrief — submit (POST) + today's own/partner-input state (GET). The
// backend persists, routes, and notifies; this is a thin scoped proxy.
export async function POST(req: NextRequest) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const user = await getCurrentUser();
  const body = (await req.json().catch(() => ({}))) as SubmitDebriefBody;
  const r = await submitDebrief(user, body);
  return r.live
    ? NextResponse.json({ ...r.data, live: true })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchDebriefsToday(user);
  return r.live ? NextResponse.json({ ...r.data, live: true }) : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
