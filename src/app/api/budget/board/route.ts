import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchBudgetBoard } from "@/lib/api/surfaces";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  const r = await fetchBudgetBoard(user, {
    fy: sp.get("fy") || undefined,
    lens: sp.get("lens") || undefined,
    month: sp.get("month") ? Number(sp.get("month")) : undefined,
    quarter: sp.get("quarter") || undefined,
    week: sp.get("week") ? Number(sp.get("week")) : undefined,
  });
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
