import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchClusters } from "@/lib/api/surfaces";

// Backend-backed cluster list (role-scoped). No mock fallback — empty array when
// the database has no clusters; error surfaced to the client.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchClusters(user);
  return r.live
    ? NextResponse.json({ live: true, clusters: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
