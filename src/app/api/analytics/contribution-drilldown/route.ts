import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchContributionDrilldown, type ContributionLens, type ContributionMetricKey } from "@/lib/api/surfaces";

// Drilldown proxy: the client "My Contribution" lens calls this on metric click.
// Scope is re-enforced by the backend against the signed-in user — this handler
// only forwards their identity, never widens scope.
export async function GET(req: NextRequest) {
  const user = await getCurrentUser();
  const sp = req.nextUrl.searchParams;
  const metric = sp.get("metric") as ContributionMetricKey | null;
  if (!metric) return NextResponse.json({ error: "metric required" }, { status: 400 });
  const lens = (sp.get("lens") as ContributionLens) ?? "own";
  const fy = sp.get("fy") ?? undefined;

  const res = await fetchContributionDrilldown(user, { metric, lens, fy });
  if (!res.live) return NextResponse.json({ rows: [], live: false, error: res.error }, { status: res.error ? 502 : 200 });
  return NextResponse.json({ rows: res.data, live: true });
}
