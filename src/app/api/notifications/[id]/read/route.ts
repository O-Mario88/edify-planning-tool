import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { markNotificationReadBE } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { id } = await params;
  const user = await getCurrentUser();
  const r = await markNotificationReadBE(user, id);
  return r.live ? NextResponse.json(r.data) : NextResponse.json({ error: r.error }, { status: 502 });
}
