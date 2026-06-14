import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser, getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";
import type { BackendMessage } from "@/components/messages/messages-store";

// Backend-backed messages (recent + counts) for the bell badge + drawer, plus
// compose (POST) — the backend message center now supports send/reply/thread.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const [recent, counts] = await Promise.all([
    backendFetch<BackendMessage[]>(`/messages/recent`, user),
    backendFetch<{ unread: number; actionRequired: number }>(`/messages/counts`, user),
  ]);
  if (!recent.ok) {
    return NextResponse.json({ live: false, error: recent.error }, { status: 502 });
  }
  return NextResponse.json({
    live: true,
    recent: recent.data,
    counts: counts.ok ? counts.data : null,
  });
}

// Compose a new message (start a thread to a recipient, context-tagged).
export async function POST(req: NextRequest) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const r = await backendFetch<{ threadId: string; id: string }>(`/messages`, user, { method: "POST", body: JSON.stringify(body) });
  return r.ok
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: 502 });
}
