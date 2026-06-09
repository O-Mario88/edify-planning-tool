import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchFundRequest } from "@/lib/api/surfaces";

// One fund request's detail — powers the dynamic detail panel. No mock.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const user = await getCurrentUser();
  const r = await fetchFundRequest(user, id);
  return r.live
    ? NextResponse.json({ live: true, request: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
