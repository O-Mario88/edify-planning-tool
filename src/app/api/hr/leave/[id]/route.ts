import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { reviewLeave } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// Approve / reject a leave request. Body: { action: "approve" | "reject" }.
// The backend re-enforces the HR/CD gate.
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { id } = await ctx.params;
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const action = body?.action === "reject" ? "reject" : "approve";
  const r = await reviewLeave(user, id, action);
  return r.live
    ? NextResponse.json({ live: true, leave: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
