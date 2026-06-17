import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchGeoMap } from "@/lib/api/surfaces";

// Proxy for the geo-analytics map (role-scoped + filter-aware). The backend
// re-enforces scope against the signed-in user; the FE choropleth joins the
// returned per-district data (keyed by official COD-AB pcode) to the boundary
// geometry in /public/geo/districts.geojson.
export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  const r = await fetchGeoMap(user, {
    region: sp.get("region") ?? undefined,
    district: sp.get("district") ?? undefined,
    cluster: sp.get("cluster") ?? undefined,
  });
  return r.live
    ? NextResponse.json({ ...r.data, live: true })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
