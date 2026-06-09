import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchCommandCenterToday } from "@/lib/api/surfaces";

// The recommendation-led home feed — role-scoped "what must I do next". No mock.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchCommandCenterToday(user);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
