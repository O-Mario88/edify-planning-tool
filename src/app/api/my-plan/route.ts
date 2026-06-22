import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchMyPlanGrouped, type BeMyPlanPeriod } from "@/lib/api/surfaces";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const user = await getCurrentUser();
  const url = new URL(req.url);
  const period = (url.searchParams.get("period") ?? "month") as BeMyPlanPeriod;
  const fy = url.searchParams.get("fy") ?? undefined;
  const r = await fetchMyPlanGrouped(user, period, fy);
  return r.live
    ? NextResponse.json(r.data)
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
