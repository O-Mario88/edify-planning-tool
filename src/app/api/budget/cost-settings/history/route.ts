import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchCostHistory } from "@/lib/api/surfaces";

// Versioned change history for the CD Country Cost Register (old→new, who, when,
// why). PLANNING_VIEW on the backend.
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const user = await getCurrentUser();
  const key = new URL(req.url).searchParams.get("key") ?? undefined;
  const r = await fetchCostHistory({ email: user.email, role: user.role }, key);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error, history: [] }, { status: r.error ? 502 : 200 });
}
