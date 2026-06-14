import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendCostPreview } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// Cost preview for the scheduling drawer — proxies to the backend CD Country
// Cost Register so the drawer shows the OFFICIAL cost (+ cost-missing), never a
// client-invented number. Returns { live:false } when the backend is off so the
// drawer can fall back to its local estimate.
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({} as Record<string, unknown>));
  const r = await backendCostPreview(
    { email: user.email, role: user.role },
    {
      activityType: String(body.activityType ?? ""),
      deliveryType: body.deliveryType as string | undefined,
      districtType: body.districtType as string | undefined,
      teachersAttended: body.teachersAttended as number | undefined,
      leadersAttended: body.leadersAttended as number | undefined,
      otherParticipants: body.otherParticipants as number | undefined,
    },
  );
  if (!r.live) return NextResponse.json({ live: false, error: r.error }, { status: 200 });
  return NextResponse.json({ live: true, ...r.data });
}
