import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchVillages } from "@/lib/api/surfaces";

// Village layer (admin5, UG-AU-DS-2022) for a given backend parishId.
export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const parishId = req.nextUrl.searchParams.get("parishId");
  if (!parishId) return NextResponse.json({ live: true, villages: [] });
  const r = await fetchVillages(user, parishId);
  return r.live
    ? NextResponse.json({ live: true, villages: r.data })
    : NextResponse.json({ live: false, villages: [], error: r.error }, { status: 502 });
}
