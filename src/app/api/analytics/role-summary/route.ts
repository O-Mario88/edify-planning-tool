// Analytics role-summary endpoint.
//
// GET /api/analytics/role-summary?fy=2026&q=Q2&region=Central&district=Mukono
// Returns the engine snapshot (metrics + breakdowns + data-quality) for the
// signed-in role, scoped by the query filters. This is the Year-2 seam: the
// mock-backed computeAnalytics swaps for a Prisma/cached query behind the same
// JSON contract. Computed live today (cache when the DB lands).

import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { computeAnalytics } from "@/lib/analytics/compute-analytics";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";

export async function GET(req: Request) {
  const user = await getCurrentUser();
  const sp = new URL(req.url).searchParams;
  const get = (k: string) => sp.get(k) ?? ALL_SENTINEL;
  const selection: FilterSelection = {
    fy: get("fy"),
    quarter: get("q"),
    region: get("region"),
    district: get("district"),
    cluster: get("cluster"),
    cceo: get("cceo"),
    partner: get("partner"),
    package: get("pkg"),
    ssa: get("ssa"),
    champion: get("champ"),
  };

  const snapshot = computeAnalytics({ selection, role: user.role, scopeLabel: user.name });

  return NextResponse.json(
    {
      scopeLabel: snapshot.scopeLabel,
      fyId: snapshot.fyId,
      cycleTag: snapshot.cycleTag,
      dataQualityScore: snapshot.dataQualityScore,
      metrics: snapshot.metrics.map((m) => ({
        key: m.key,
        label: m.label,
        group: m.group,
        value: m.value,
        breakdown: m.breakdown,
        definition: m.definition,
      })),
      pipeline: snapshot.pipeline.map((s) => ({ key: s.key, label: s.label, count: s.count })),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
