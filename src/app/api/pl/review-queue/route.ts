import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchPlReviewQueue } from "@/lib/api/surfaces";

export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchPlReviewQueue(user);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
