import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendPartnerScheduleActivity } from "@/lib/api/surfaces";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const user = await getCurrentUser();
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  const r = await backendPartnerScheduleActivity(user, id, body);
  return r.live
    ? NextResponse.json({ live: true, activity: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
