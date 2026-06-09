import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchClusterPlanning } from "@/lib/api/surfaces";

// Per-cluster meeting-slot planning status (SIT + 1st/2nd/3rd), derived from
// real cluster activities. Role-scoped, no mock.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchClusterPlanning(user);
  return r.live
    ? NextResponse.json({ live: true, clusters: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
