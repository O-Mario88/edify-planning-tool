import { NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// The live notification rail (spec §12) — active notifications grouped by
// priority, each with its full action contract (route + label + context).
export const dynamic = "force-dynamic";

type RailItem = {
  id: string; title: string; body: string | null;
  priority: "low" | "normal" | "high" | "urgent";
  contextType: string | null; contextId: string | null; targetRoute: string | null;
  actionLabel: string | null; actionRequired: boolean;
  status: string; createdAt: string; expiresAt: string | null;
  sourceEventType: string | null; sourceEventId: string | null;
};
export type NotificationRail = { unread: number; total: number; groups: { priority: string; items: RailItem[] }[] };

export async function GET() {
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const r = await backendFetch<NotificationRail>(`/notifications/rail`, user);
  return r.ok
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: 200 });
}
