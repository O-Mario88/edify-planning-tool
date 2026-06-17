import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchSsaPerformanceGrouped, fetchSsaDrilldown } from "@/lib/api/surfaces";

// Proxy for the backend SSA-performance grid (grouped + drilldown). Scope is
// re-enforced by the backend against the signed-in user.
export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  const fy = sp.get("fy") ?? undefined;
  const schoolType = sp.get("schoolType") ?? undefined;
  const groupBy = sp.get("groupBy") ?? "district";
  // Geography filter from the bar — forwarded so the grid narrows server-side.
  const region = sp.get("region") ?? undefined;
  const district = sp.get("district") ?? undefined;
  const cluster = sp.get("cluster") ?? undefined;

  if (sp.get("drilldown") === "1") {
    const groupId = sp.get("groupId");
    if (!groupId) return NextResponse.json({ error: "groupId required" }, { status: 400 });
    const r = await fetchSsaDrilldown(user, { groupBy, groupId, fy, schoolType });
    return r.live ? NextResponse.json({ rows: r.data, live: true }) : NextResponse.json({ rows: [], live: false, error: r.error }, { status: r.error ? 502 : 200 });
  }

  const r = await fetchSsaPerformanceGrouped(user, { groupBy, schoolType, fy, region, district, cluster });
  return r.live ? NextResponse.json({ ...r.data, live: true }) : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
