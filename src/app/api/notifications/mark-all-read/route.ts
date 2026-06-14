import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { markAllNotificationsReadBE } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

export async function PATCH(req: Request) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const user = await getCurrentUser();
  const r = await markAllNotificationsReadBE(user);
  return r.live ? NextResponse.json(r.data) : NextResponse.json({ error: r.error }, { status: 502 });
}
