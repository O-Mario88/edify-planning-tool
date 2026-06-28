import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchMyTargets } from "@/lib/api/surfaces";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  const r = await fetchMyTargets(
    user,
    sp.get("fy") ?? undefined,
    sp.get("period") ?? undefined
  );
  return r.live
    ? NextResponse.json({ ...r.data, live: true })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
