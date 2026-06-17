import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchGeoDistrictDetail } from "@/lib/api/surfaces";

// Lazy district detail for the map drawer — clusters in the district, each with
// its own SSA average + weakest intervention. Role-scoped by the backend.
export async function GET(_req: NextRequest, { params }: { params: Promise<{ districtId: string }> }) {
  const { districtId } = await params;
  const user = await getCurrentUser();
  const r = await fetchGeoDistrictDetail(user, districtId);
  return r.live
    ? NextResponse.json({ ...r.data, live: true })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
