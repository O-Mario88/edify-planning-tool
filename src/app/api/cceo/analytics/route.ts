// GET /api/cceo/analytics — the workflow-derived analytics snapshot
// (src/lib/analytics) scoped to the signed-in viewer, same contract as
// /api/analytics/role-summary but behind the CCEO guard. Supports the
// filter dimensions the engine reads: ?fy= ?q= ?region= ?district=
// ?cluster= ?partner= ?pkg= ?ssa= ?champ= (?week=/?month= are ignored —
// the engine works in FY/quarter cycles).

import type { NextRequest } from "next/server";
import { requireCceo, ok } from "../_auth";
import { computeAnalytics } from "@/lib/analytics/compute-analytics";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const sp = req.nextUrl.searchParams;
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

  const snapshot = computeAnalytics({
    selection,
    role: user.role,
    scopeLabel: user.name,
  });

  return ok({
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
  });
}
