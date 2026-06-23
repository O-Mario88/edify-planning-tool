import { NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// Persistent command-center alerts (spec §13/§17) — operational risks generated
// from live data conditions; reappear while unresolved.
export const dynamic = "force-dynamic";

export type CommandCenterAlert = {
  id: string;
  alertType: string;
  severity: "low" | "normal" | "high" | "urgent";
  scope: string | null;
  title: string;
  body: string | null;
  targetRoute: string | null;
  contextType: string | null;
  contextId: string | null;
  createdAt: string;
};

export async function GET() {
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const r = await backendFetch<CommandCenterAlert[]>(`/command-center/alerts`, user);
  return r.ok
    ? NextResponse.json({ live: true, alerts: r.data })
    : NextResponse.json({ live: false, alerts: [], error: r.error }, { status: 200 });
}
