import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchPlanningSetup } from "@/lib/api/surfaces";

// Planning setup buckets — schools by planning stage (scoped). No mock.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const r = await fetchPlanningSetup(user, req.nextUrl.search);
  return r.live
    ? NextResponse.json({ live: true, buckets: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
