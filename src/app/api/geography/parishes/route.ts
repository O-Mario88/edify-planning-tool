import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchDistricts, fetchSubCounties, fetchParishes } from "@/lib/api/surfaces";

// Parish layer (UG-AU-DS-2022). Accepts either a backend `subCountyId` directly,
// or `district` + `subCounty` NAMES which it resolves to the backend sub-county
// id (so name-based forms like Add-School can cascade without holding ids).
export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  let subCountyId = sp.get("subCountyId") ?? undefined;
  const district = sp.get("district");
  const subCounty = sp.get("subCounty");

  if (!subCountyId && district && subCounty) {
    const dRes = await fetchDistricts(user);
    if (!dRes.live) return NextResponse.json({ live: false, parishes: [] }, { status: 502 });
    const d = dRes.data.find((x) => x.name.toLowerCase() === district.toLowerCase());
    if (!d) return NextResponse.json({ live: true, parishes: [], subCountyId: null });
    const scRes = await fetchSubCounties(user, d.id);
    if (scRes.live) subCountyId = scRes.data.find((x) => x.name.toLowerCase() === subCounty.toLowerCase())?.id;
  }
  if (!subCountyId) return NextResponse.json({ live: true, parishes: [], subCountyId: null });

  const pRes = await fetchParishes(user, subCountyId);
  return pRes.live
    ? NextResponse.json({ live: true, parishes: pRes.data, subCountyId })
    : NextResponse.json({ live: false, parishes: [], error: pRes.error }, { status: 502 });
}
