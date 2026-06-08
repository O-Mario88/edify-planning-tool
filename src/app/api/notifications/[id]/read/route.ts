import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { markNotificationReadBE } from "@/lib/api/surfaces";

export async function PATCH(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const r = await markNotificationReadBE(user, id);
  return r.live ? NextResponse.json(r.data) : NextResponse.json({ error: r.error }, { status: 502 });
}
