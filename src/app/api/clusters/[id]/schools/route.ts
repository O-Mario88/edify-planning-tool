import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchClusterSchools } from "@/lib/api/surfaces";

// Backend-backed member schools for a single cluster (role-scoped). No mock
// fallback — empty list when the cluster has no schools; error surfaced to the
// client (502) when the backend request fails.
export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const r = await fetchClusterSchools(user, id);
  return r.live
    ? NextResponse.json({ live: true, ...r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
