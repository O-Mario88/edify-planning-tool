import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchAssignmentOptions } from "@/lib/api/surfaces";

// Role + capacity-aware assignment targets for a school (self / supervised CCEO
// / partner). Drives the live Assign drawer's owner options. No mock.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const schoolId = req.nextUrl.searchParams.get("schoolId") ?? "";
  const fy = req.nextUrl.searchParams.get("fy") ?? undefined;
  if (!schoolId) return NextResponse.json({ live: false, error: "schoolId required" }, { status: 400 });
  const r = await fetchAssignmentOptions(user, schoolId, fy);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
