import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchApprovedLeave } from "@/lib/api/surfaces";

// Approved leave shaped for the calendar + planning availability. HR/CD see the
// team; a staffer sees their own. Used to overlay leave on /calendar and to
// block a planner's own leave days in the planning calendar.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const from = req.nextUrl.searchParams.get("from") ?? undefined;
  const to = req.nextUrl.searchParams.get("to") ?? undefined;
  const r = await fetchApprovedLeave(user, { from, to });
  return r.live
    ? NextResponse.json({ live: true, leave: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
