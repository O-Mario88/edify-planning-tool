import { NextRequest, NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";

// Reply on an existing message thread.
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { id } = await ctx.params;
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const r = await backendFetch<{ threadId: string; id: string }>(`/messages/${encodeURIComponent(id)}/reply`, user, { method: "POST", body: JSON.stringify(body) });
  return r.ok
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: 502 });
}
