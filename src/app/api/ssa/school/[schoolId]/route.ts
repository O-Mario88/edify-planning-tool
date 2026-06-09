import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchSsaForSchool } from "@/lib/api/surfaces";

// The selected school's SSA history (the View SSA drawer) — not a general grid.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: { params: Promise<{ schoolId: string }> }) {
  const { schoolId } = await ctx.params;
  const user = await getCurrentUser();
  const r = await fetchSsaForSchool(user, schoolId);
  return r.live
    ? NextResponse.json({ live: true, records: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
