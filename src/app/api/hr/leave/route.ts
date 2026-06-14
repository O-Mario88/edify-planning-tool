import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchLeave, requestLeave } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// Leave requests. GET: HR/CD see all, a staffer sees their own (the backend
// scopes by the caller's staff profile). POST: request leave. `canReview`
// tells the UI whether to show approve/reject controls.
export const dynamic = "force-dynamic";

const REVIEW_ROLES = new Set(["HumanResource", "HumanResources", "CountryDirector", "Admin"]);

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchLeave(user);
  const canReview = REVIEW_ROLES.has(user.role);
  return r.live
    ? NextResponse.json({ live: true, leave: r.data, canReview })
    : NextResponse.json({ live: false, error: r.error, canReview }, { status: r.error ? 502 : 200 });
}

export async function POST(req: NextRequest) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  if (!body?.startDate || !body?.endDate) {
    return NextResponse.json({ error: "startDate and endDate are required" }, { status: 400 });
  }
  const r = await requestLeave(user, {
    type: body.type, startDate: body.startDate, endDate: body.endDate,
    days: typeof body.days === "number" ? body.days : undefined, reason: body.reason,
  });
  return r.live
    ? NextResponse.json({ live: true, leave: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
