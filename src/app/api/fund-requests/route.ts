import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchFundRequests } from "@/lib/api/surfaces";

// Fund-request queue — role-scoped (approvers see all; submitters see own). No mock.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchFundRequests(user);
  return r.live
    ? NextResponse.json({ live: true, requests: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
