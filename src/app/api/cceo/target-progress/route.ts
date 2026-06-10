// GET /api/cceo/target-progress — the cumulative period-target read
// (Q1 25% · Mid-Year 50% · Q3 75% · FY 100%), built from the same engines
// the /schools header uses: portfolioForStaffId (the viewer's owned schools,
// "supported" = SSA done or active partner) through computePeriodTarget.
// Also reports the role's annual activity target (CCEO 560). Supports
// ?fy=2026 and ?quarter=Q1..Q4 (alias ?q=); ?week=/?month= are ignored.

import type { NextRequest } from "next/server";
import { requireCceo, ok, type NextAction } from "../_auth";
import { computePeriodTarget } from "@/lib/targets/period-target";
import { fyTargetForRole, CCEO_ANNUAL_TARGET } from "@/lib/targets/role-targets";
import { portfolioForStaffId } from "@/lib/portfolio/portfolio";
import { schoolIdsWithActivePartner } from "@/lib/portfolio/partner-assignments";
import { deriveQuarterFromDate } from "@/lib/intake/intake-core";
import { engineNowIso } from "@/lib/clock";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const sp = req.nextUrl.searchParams;
  const selectedFy = sp.get("fy") ?? undefined;
  const quarterParam = sp.get("quarter") ?? sp.get("q");
  const selectedQuarter =
    quarterParam && /^Q[1-4]$/.test(quarterParam)
      ? quarterParam
      : deriveQuarterFromDate(engineNowIso());

  // Portfolio coverage target: every owned school supported (SSA done or
  // an active partner on it), cumulative across the FY.
  const portfolio = portfolioForStaffId(user.staffId);
  const withPartner = schoolIdsWithActivePartner();
  const supported = portfolio.schools.filter(
    (s) => s.ssaStatus === "SSA Done" || withPartner.has(s.schoolId),
  ).length;

  const periodTarget = computePeriodTarget({
    fyTarget: portfolio.schools.length,
    achieved: supported,
    selectedFy,
    selectedQuarter,
  });

  const nextActions: NextAction[] = [];
  if (periodTarget.gapToExpected < 0) {
    nextActions.push({
      label: `Close the pace gap (${Math.abs(periodTarget.gapToExpected)} schools behind)`,
      reason: `Expected ${periodTarget.expectedCumulative} supported by ${selectedQuarter}, currently ${periodTarget.achieved} — risk ${periodTarget.riskLevel}.`,
      href: "/planning",
    });
  }

  return ok(
    {
      role: user.role,
      annualActivityTarget: user.role === "CCEO" ? CCEO_ANNUAL_TARGET : fyTargetForRole(user.role),
      portfolio: {
        staffId: portfolio.staffId,
        schools: portfolio.schools.length,
        supported,
        counts: portfolio.counts,
      },
      selectedQuarter,
      periodTarget,
    },
    nextActions,
  );
}
