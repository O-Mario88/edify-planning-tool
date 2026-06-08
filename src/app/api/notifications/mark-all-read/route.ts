import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { markAllNotificationsReadBE } from "@/lib/api/surfaces";

export async function PATCH() {
  const user = await getCurrentUser();
  const r = await markAllNotificationsReadBE(user);
  return r.live ? NextResponse.json(r.data) : NextResponse.json({ error: r.error }, { status: 502 });
}
