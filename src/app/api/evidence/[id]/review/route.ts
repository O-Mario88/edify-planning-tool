import { NextRequest, NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch, isBackendEnabled } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";

// Staff / PL / IA accept or return an uploaded evidence file. Drives
// Activity.evidenceStatus on the backend (the real IA / payment gate).
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { id } = await ctx.params;
  if (!isBackendEnabled()) return NextResponse.json({ error: "Backend disabled" }, { status: 503 });
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const action = body?.action === "return" ? "return" : "accept";
  const r = await backendFetch<{ id: string; status: string }>(
    `/evidence/${encodeURIComponent(id)}/review`, user,
    { method: "POST", body: JSON.stringify({ action, note: body?.note }) },
  );
  return r.ok
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
