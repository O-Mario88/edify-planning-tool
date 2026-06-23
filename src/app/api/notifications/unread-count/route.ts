import { NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// The unread notification badge number (spec §17).
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const r = await backendFetch<{ count: number }>(`/notifications/unread-count`, user);
  return r.ok
    ? NextResponse.json({ live: true, count: r.data.count })
    : NextResponse.json({ live: false, count: 0, error: r.error }, { status: 200 });
}
