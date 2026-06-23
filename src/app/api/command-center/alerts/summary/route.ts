import { NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// Severity-bucketed counts for the command-center header (spec §17).
export const dynamic = "force-dynamic";

export type AlertSummary = { total: number; urgent: number; high: number; normal: number; low: number };

export async function GET() {
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const r = await backendFetch<AlertSummary>(`/command-center/alerts/summary`, user);
  return r.ok
    ? NextResponse.json({ live: true, summary: r.data })
    : NextResponse.json({ live: false, summary: null, error: r.error }, { status: 200 });
}
