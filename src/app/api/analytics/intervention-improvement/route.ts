import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchInterventionImprovement } from "@/lib/api/surfaces";

// Proxy for the backend intervention-improvement grid (scope re-enforced by the backend).
export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  const r = await fetchInterventionImprovement(user, {
    groupBy: sp.get("groupBy") ?? undefined,
    schoolType: sp.get("schoolType") ?? undefined,
    currentFy: sp.get("currentFy") ?? undefined,
    prevFy: sp.get("prevFy") ?? undefined,
  });
  return r.live ? NextResponse.json({ ...r.data, live: true }) : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
