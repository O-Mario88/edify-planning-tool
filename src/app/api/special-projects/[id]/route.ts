import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchProjectDetail } from "@/lib/api/surfaces";

// A project's detail (assigned schools + partners) — backend, no mock.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const r = await fetchProjectDetail(user, id);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
