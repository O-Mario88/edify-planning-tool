import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchRecruitmentRecommendation } from "@/lib/api/surfaces";

// Recruitment Intelligence proxy. The backend re-enforces both scope and the
// RECRUITMENT_INTELLIGENCE_VIEW permission (HR/Accountant/Partner are blocked).
export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  const r = await fetchRecruitmentRecommendation(user, {
    fy: sp.get("fy") ?? undefined,
    districtId: sp.get("districtId") ?? undefined,
  });
  return r.live ? NextResponse.json({ ...r.data, live: true }) : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
