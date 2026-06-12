import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchPartners } from "@/lib/api/surfaces";

// Active partners for assignment pickers (real backend partner IDs). No mock.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchPartners(user, true);
  return r.live
    ? NextResponse.json({ live: true, partners: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
