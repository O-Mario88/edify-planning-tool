// GET /api/cceo/reports — the CCEO report catalogue (spec §21): the seven
// auto-generated reports assembled from records the CCEO already produces
// (cceoAutoReports), plus the shared recent/scheduled report lists from the
// same module for context. ?fy=/?week=/?month= are ignored (each report
// carries its own freshness window).

import { requireCceo, ok, type NextAction } from "../_auth";
import { cceoAutoReports, recentReports, scheduledReports } from "@/lib/reports-types";

export const dynamic = "force-dynamic";

export async function GET() {
  const g = await requireCceo();
  if (g.error) return g.error;

  const nextActions: NextAction[] = cceoAutoReports.slice(0, 2).map((r) => ({
    label: `Review ${r.title}`,
    reason: `${r.cadence} report — ${r.freshness}.`,
    href: r.liveHref,
  }));

  return ok(
    {
      autoReports: cceoAutoReports,
      recent: recentReports,
      scheduled: scheduledReports,
    },
    nextActions,
  );
}
