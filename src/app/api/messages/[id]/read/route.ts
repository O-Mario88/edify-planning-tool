import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// Mark a single inbox message read. Mirrors /api/notifications/[id]/read.
export async function PATCH(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const r = await backendFetch<{ status: string }>(`/messages/${encodeURIComponent(id)}/read`, user, { method: "PATCH" });
  return r.ok ? NextResponse.json(r.data) : NextResponse.json({ error: r.error }, { status: 502 });
}
