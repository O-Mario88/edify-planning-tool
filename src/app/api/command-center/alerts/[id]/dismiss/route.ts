import { NextRequest, NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";

// Dismiss a command-center alert for this user for a window (spec §13). The
// alert reappears once the window lapses if the issue is still unresolved.
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { id } = await params;
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const r = await backendFetch<{ ok: boolean; dismissedUntil?: string }>(`/command-center/alerts/${encodeURIComponent(id)}/dismiss`, user, {
    method: "POST",
    body: JSON.stringify({ hours: body?.hours }),
  });
  return r.ok
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: 502 });
}
