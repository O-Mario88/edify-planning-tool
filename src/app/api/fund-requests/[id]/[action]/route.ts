import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { reviewFundRequest } from "@/lib/api/surfaces";

// Approve / return / reject a fund request (backend gates on BUDGET_APPROVE).
export const dynamic = "force-dynamic";
const ACTIONS = new Set(["approve", "return", "reject"]);

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string; action: string }> }) {
  const { id, action } = await ctx.params;
  if (!ACTIONS.has(action)) return NextResponse.json({ live: false, error: `Unknown action: ${action}` }, { status: 400 });
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await reviewFundRequest(user, id, action as "approve" | "return" | "reject", body?.note);
  return r.live
    ? NextResponse.json({ live: true, request: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
