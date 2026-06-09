import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { activityAction } from "@/lib/api/surfaces";

// Activity row actions — the workflow state machine, backend-enforced.
export const dynamic = "force-dynamic";

const ACTIONS = new Set([
  "complete", "ia-confirm", "reschedule", "reassign", "cancel", "defer", "clear-payment",
]);

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string; action: string }> }) {
  const { id, action } = await ctx.params;
  if (!ACTIONS.has(action)) {
    return NextResponse.json({ live: false, error: `Unknown action: ${action}` }, { status: 400 });
  }
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await activityAction(user, id, action, body);
  return r.live
    ? NextResponse.json({ live: true, data: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
