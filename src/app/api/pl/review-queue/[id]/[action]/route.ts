import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendPlReviewAction } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

export const dynamic = "force-dynamic";

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string; action: string }> },
) {
  const csrf = enforceCsrf(req);
  if (csrf) return csrf;
  const { id, action } = await ctx.params;
  if (action !== "confirm" && action !== "return") {
    return NextResponse.json({ live: false, error: `Unknown action: ${action}` }, { status: 400 });
  }
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await backendPlReviewAction(user, id, action, body);
  return r.live
    ? NextResponse.json({ live: true, data: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
