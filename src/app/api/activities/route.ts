import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchActivities, backendCreateActivity } from "@/lib/api/surfaces";

// Activities list (My Plan / scoped) + schedule. No mock.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const qs = req.nextUrl.search; // pass through ?mine=&status=&fy=…
  const r = await fetchActivities(user, qs);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}

export async function POST(req: NextRequest) {
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await backendCreateActivity(user, body);
  return r.live
    ? NextResponse.json({ live: true, data: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
