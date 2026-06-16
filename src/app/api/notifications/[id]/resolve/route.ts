import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { resolveNotificationBE } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// PATCH /api/notifications/:id/resolve — mark a notification resolved (the issue
// it points to is handled). Resolved notifications leave the active feed + badge.
export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { id } = await params;
  const user = await getCurrentUser();
  const r = await resolveNotificationBE(user, id);
  return r.live ? NextResponse.json(r.data) : NextResponse.json({ error: r.error }, { status: 502 });
}
