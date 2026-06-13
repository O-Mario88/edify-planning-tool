import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchProjectImpact } from "@/lib/api/surfaces";

// Project impact: per-school baseline vs latest SSA on the target intervention.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const r = await fetchProjectImpact(user, id);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
