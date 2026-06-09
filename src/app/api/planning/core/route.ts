import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchPlanningCore } from "@/lib/api/surfaces";

// Core-school planning (4 visits + 4 trainings package), scoped. No mock.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const r = await fetchPlanningCore(user, req.nextUrl.search);
  return r.live
    ? NextResponse.json({ live: true, core: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
