import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchSsaRecommendation } from "@/lib/api/surfaces";

// SSA-driven recommendation for a school (two weakest interventions + severity),
// computed by the backend from real SsaRecord scores — the canonical source that
// replaces the empty in-memory mock rec-engine. Consumers call this when the
// backend is enabled and fall back to their local engine otherwise.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: { params: Promise<{ schoolId: string }> }) {
  const { schoolId } = await ctx.params;
  const user = await getCurrentUser();
  const r = await fetchSsaRecommendation(user, schoolId);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
