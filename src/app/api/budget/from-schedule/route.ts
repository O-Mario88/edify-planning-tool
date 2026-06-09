import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchBudgetFromSchedule } from "@/lib/api/surfaces";

// Annual budget built from the caller's scheduled activities + busy/slow-month
// intelligence. Role-scoped, auto-costed from the CD rate card. No mock.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const fy = req.nextUrl.searchParams.get("fy") || undefined;
  const r = await fetchBudgetFromSchedule(user, fy);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
