import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";
import type { BackendMessage } from "@/components/messages/messages-store";

// Backend-backed messages (recent + counts) for the bell badge + drawer.
// Mirrors the notifications proxy. No mock fallback — when the backend is off
// or the inbox is empty, the client renders a loading/empty/error state.
//
// The backend messages module is intentionally thin (GET /messages/recent,
// GET /messages/counts, PATCH /messages/:id/read). Thread bodies / compose are
// NOT wired here — the full message center has no backend yet.
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
