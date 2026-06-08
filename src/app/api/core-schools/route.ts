import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchCoreHeader, fetchSchools } from "@/lib/api/surfaces";

// Backend-backed Core School Directory (role-scoped). Reuses the shared
// surfaces fetchers: /filters/core-header-summary for the KPI pills and
// /schools?schoolType=core for the directory rows. No mock fallback — empty
// arrays when the database has no core schools; error surfaced to the client.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const [h, s] = await Promise.all([fetchCoreHeader(user), fetchSchools(user, { schoolType: "core" })]);

  if (h.live && s.live) {
    return NextResponse.json({ live: true, header: h.data, schools: s.data.data, total: s.data.total });
  }
  const error = (!h.live && h.error) || (!s.live && s.error) || null;
  return NextResponse.json({ live: false, error }, { status: error ? 502 : 200 });
}
