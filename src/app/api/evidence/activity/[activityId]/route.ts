import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch, isBackendEnabled } from "@/lib/api/backend";

// List the evidence files attached to an activity (for upload UI + review).
export const dynamic = "force-dynamic";

export type EvidenceItem = {
  id: string; kind: string; status: string; originalName: string | null;
  mimeType: string | null; uploadedBy: string; uploadedAt: string; reviewNote: string | null;
};

export async function GET(_req: Request, ctx: { params: Promise<{ activityId: string }> }) {
  const { activityId } = await ctx.params;
  if (!isBackendEnabled()) return NextResponse.json({ live: false, evidence: [] });
  const user = await getCurrentUser();
  const r = await backendFetch<EvidenceItem[]>(`/evidence/activity/${encodeURIComponent(activityId)}`, user);
  return r.ok
    ? NextResponse.json({ live: true, evidence: r.data })
    : NextResponse.json({ live: false, evidence: [], error: r.error }, { status: 200 });
}
