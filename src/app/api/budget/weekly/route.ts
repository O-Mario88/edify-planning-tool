import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchBudgetWeekly } from "@/lib/api/surfaces";

// Weekly fund request — line-item-costed scheduled activities for CCEO/PL.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const fy = req.nextUrl.searchParams.get("fy") || undefined;
  const monthRaw = req.nextUrl.searchParams.get("month");
  const month = monthRaw ? Number(monthRaw) : undefined;
  const r = await fetchBudgetWeekly(user, { fy, month });
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
