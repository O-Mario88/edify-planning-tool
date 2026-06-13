import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchStaffCapacity } from "@/lib/api/surfaces";

// The caller's (or a named staff's) direct-support capacity. No mock.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const staffId = req.nextUrl.searchParams.get("staffId") ?? undefined;
  const fy = req.nextUrl.searchParams.get("fy") ?? undefined;
  const r = await fetchStaffCapacity(user, staffId, fy);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
