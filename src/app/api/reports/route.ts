import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchReports, generateReport } from "@/lib/api/surfaces";

// Generated, persisted program reports. GET lists; POST generates one from
// live program data and persists it. Backend re-enforces ANALYTICS_VIEW.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchReports(user);
  return r.live
    ? NextResponse.json({ live: true, reports: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}

export async function POST(req: NextRequest) {
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const type = typeof body?.type === "string" ? body.type : "program_summary";
  const fy = typeof body?.fy === "string" ? body.fy : "2026";
  const r = await generateReport(user, type, fy);
  return r.live
    ? NextResponse.json({ live: true, report: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
