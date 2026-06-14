import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendUpdateFlag } from "@/lib/api/surfaces";

// PL acknowledges/resolves a CD flag.
export const dynamic = "force-dynamic";

export async function PATCH(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await backendUpdateFlag({ email: user.email, role: user.role }, id, {
    action: body.action === "resolve" ? "resolve" : "acknowledge",
    note: body.note,
  });
  return r.live
    ? NextResponse.json({ live: true, flag: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: 502 });
}
