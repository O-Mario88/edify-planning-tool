import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { mergePartnerDebrief } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// CCEO merges a reviewed partner debrief into their daily debrief; the backend
// links (never overwrites) the partner record, flips both to merged, and routes
// the combined record up to PL/CD/IA/HR.
export async function POST(req: NextRequest) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const partnerDebriefId = typeof body?.partnerDebriefId === "string" ? body.partnerDebriefId : "";
  if (!partnerDebriefId) return NextResponse.json({ error: "partnerDebriefId required" }, { status: 400 });
  const r = await mergePartnerDebrief(user, { partnerDebriefId, cceoDebriefId: body.cceoDebriefId, note: body.note });
  return r.live
    ? NextResponse.json({ ...r.data, live: true })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
