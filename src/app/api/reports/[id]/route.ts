import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchReport } from "@/lib/api/surfaces";

// A single generated report including its persisted summaryJson snapshot.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const user = await getCurrentUser();
  const r = await fetchReport(user, id);
  return r.live
    ? NextResponse.json({ live: true, report: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
