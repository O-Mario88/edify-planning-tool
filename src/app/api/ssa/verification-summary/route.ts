import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchSsaVerificationSummary } from "@/lib/api/surfaces";

// Team/country 10% SSA verification QA rollup (role-scoped). No mock fallback.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchSsaVerificationSummary(user);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
