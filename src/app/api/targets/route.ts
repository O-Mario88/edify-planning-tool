import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchTargetsByPeriod } from "@/lib/api/surfaces";

// The caller's target progress by period (staff + partner + total). No mock.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const fy = req.nextUrl.searchParams.get("fy") ?? undefined;
  const staffId = req.nextUrl.searchParams.get("staffId") ?? undefined;
  const r = await fetchTargetsByPeriod(user, fy, staffId);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
