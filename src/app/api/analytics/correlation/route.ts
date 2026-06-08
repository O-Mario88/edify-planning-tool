import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchSupportSsaCorrelation, fetchStaffVsPartner } from "@/lib/api/surfaces";

// Layer 3 proxy: support-to-improvement correlation + staff-vs-partner split.
// Both backend calls run in parallel; scope is re-enforced server-side.
export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  const params = {
    support: sp.get("support") ?? undefined,
    schoolType: sp.get("schoolType") ?? undefined,
    districtId: sp.get("districtId") ?? undefined,
    regionId: sp.get("regionId") ?? undefined,
  };
  const [corr, svp] = await Promise.all([
    fetchSupportSsaCorrelation(user, params),
    fetchStaffVsPartner(user, params),
  ]);
  if (!corr.live) return NextResponse.json({ live: false, error: corr.error }, { status: corr.error ? 502 : 200 });
  return NextResponse.json({ live: true, correlation: corr.data, staffVsPartner: svp.live ? svp.data : null });
}
