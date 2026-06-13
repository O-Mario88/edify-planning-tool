import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { removeProjectPartner } from "@/lib/api/surfaces";

// Remove a partner from a project. Backend.
export const dynamic = "force-dynamic";

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string; partnerId: string }> }) {
  const { id, partnerId } = await params;
  const user = await getCurrentUser();
  const r = await removeProjectPartner(user, id, partnerId);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
