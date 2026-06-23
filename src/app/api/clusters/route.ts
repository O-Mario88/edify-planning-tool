import { NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { fetchClusters } from "@/lib/api/surfaces";

// Backend-backed cluster list (role-scoped). No mock fallback — empty array when
// the database has no clusters; error surfaced to the client.
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const user = await getCurrentUserOrNull();
    if (!user) {
      return NextResponse.json({ live: false, error: "Sign in required." }, { status: 401 });
    }
    const r = await fetchClusters({ email: user.email, role: user.role });
    if (r.live) {
      return NextResponse.json({ live: true, clusters: r.data });
    }
    return NextResponse.json(
      { live: false, error: r.error ?? "Could not load clusters from edify-api." },
      { status: 502 },
    );
  } catch (e) {
    const message = e instanceof Error ? e.message : "Cluster list failed";
    return NextResponse.json({ live: false, error: message }, { status: 500 });
  }
}
