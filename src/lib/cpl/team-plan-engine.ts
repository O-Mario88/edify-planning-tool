// Team Plan engine — the PL's one-screen answer to "what are my CCEOs
// doing and where is the team slipping?" without opening every CCEO page.
//
// One row per supervised CCEO, joining the three sources that already
// exist for other surfaces (never inventing new numbers):
//   • org/supervision.ts        → who reports to this PL
//   • team-targets-mock.ts      → targets, pace, category progress, the
//                                 context flags that explain gaps
//   • portfolio/portfolio.ts    → the CCEO's actual school portfolio
//                                 (core/client split, missing SSA,
//                                 cluster gate, partner delegations)
//
// When the backend lands, GET /api/pl/team-plan returns this same
// TeamPlanRow shape — this file is the swap seam.

import { cceosSupervisedBy } from "@/lib/org/supervision";
import {
  staffTargetPerformance,
  type StaffTargetRow,
} from "@/lib/team-targets-mock";
import {
  portfolioForStaffId,
  type PortfolioCounts,
} from "@/lib/portfolio/portfolio";
import { activities } from "@/lib/actions/store";

// Activity statuses that count as "done" for the team-plan pace card.
// Matches the cumulative-target ledger in fy-target-filter-engine —
// Completed unlocks all downstream verification, so PL sees the same
// number their CCEO sees as "done this month".
const DONE_STATUSES: ReadonlySet<string> = new Set([
  "Completed",
  "SubmittedForVerification",
  "SalesforceIdPending",
  "Verified",
  "AccountabilityClosed",
]);

function liveMonthCounts(staffId: string, now: Date = new Date()): {
  completed: number;
  scheduledThisMonth: number;
} {
  const y = now.getFullYear();
  const m = now.getMonth();
  let completed = 0;
  let scheduledThisMonth = 0;
  for (const a of activities()) {
    if (a.assigneeId !== staffId) continue;
    if (a.deliveryType === "partner") continue; // partner-delivered doesn't count toward staff pace
    // Anchor on scheduledDate when present, else updatedAt — same
    // disambiguation the My Plan + targets engines use.
    const anchorIso = a.scheduledDate ?? a.updatedAt;
    const d = new Date(anchorIso);
    if (Number.isNaN(d.getTime())) continue;
    if (d.getFullYear() !== y || d.getMonth() !== m) continue;
    scheduledThisMonth++;
    if (DONE_STATUSES.has(a.status)) completed++;
  }
  return { completed, scheduledThisMonth };
}

// The five supervision labels from the PL spec. One label per CCEO;
// when several apply, the most actionable wins (worst-first precedence
// below) and the others surface in `statusReasons`.
export type TeamPlanStatus =
  | "On Track"
  | "Needs Attention"
  | "Behind Target"
  | "Overloaded"
  | "Data Quality Issue";

export type TeamPlanRow = {
  staffId: string;
  name: string;
  initials: string;
  region: string;

  status: TeamPlanStatus;
  /** Every applicable signal, lead reason first — shown on the card. */
  statusReasons: string[];

  // Plan pacing (monthly activity numbers from the target engine).
  monthlyTarget: number;
  completedThisMonth: number;
  remainingThisMonth: number;
  /** Remaining work spread over the rest of the month — the weekly pace
   *  the CCEO must hold to land the month. */
  weeklyPaceNeeded: number;
  achievementPercent: number;
  paceStatus: StaffTargetRow["paceStatus"];

  // Portfolio gaps (real school counts from the intake portfolio).
  portfolio: Pick<
    PortfolioCounts,
    "total" | "client" | "core" | "missingSsa" | "unclustered" | "partnerAssigned"
  >;

  // Category progress (cumulative % against period target).
  categories: {
    visits: number;
    trainings: number;
    ssa: number;
    salesforce: number;
    corePackage: number;
  };

  // Verification / data-quality signals.
  salesforceCompliancePercent: number;
  unresolvedSalesforceIssues: number;

  // Fund/blocker context (explains gaps before any escalation).
  fundingDelayDays: number;
  blockedPlanningDays: number;
  partnerDependencyBlocks: number;
  approvedLeaveDays: number;

  recommendedSupportActions: string[];
};

export type TeamPlanSummary = {
  cceos: number;
  byStatus: Record<TeamPlanStatus, number>;
  schoolsMissingSsa: number;
  schoolsUnclustered: number;
  totalRemainingThisMonth: number;
};

const STATUS_ORDER: TeamPlanStatus[] = [
  "Behind Target",
  "Overloaded",
  "Data Quality Issue",
  "Needs Attention",
  "On Track",
];

function classify(t: StaffTargetRow): { status: TeamPlanStatus; reasons: string[] } {
  const reasons: string[] = [];
  const behind =
    t.paceStatus === "Behind" || t.paceStatus === "High Risk" || t.paceStatus === "Critical";
  if (behind) reasons.push(`${t.paceStatus} — ${t.achievementPercent}% of expected pace`);

  const overloaded =
    t.routeDifficultyIndex >= 70 || t.blockedPlanningDays >= 3 || t.partnerDependencyBlocks >= 2;
  if (overloaded) {
    if (t.routeDifficultyIndex >= 70) reasons.push(`Route difficulty ${t.routeDifficultyIndex}/100`);
    if (t.blockedPlanningDays >= 3) reasons.push(`${t.blockedPlanningDays} blocked planning days`);
    if (t.partnerDependencyBlocks >= 2) reasons.push(`${t.partnerDependencyBlocks} partner dependency blocks`);
  }

  const dataQuality = t.salesforceCompliancePercent < 70 || t.unresolvedSalesforceIssues >= 3;
  if (dataQuality) {
    reasons.push(
      t.salesforceCompliancePercent < 70
        ? `Salesforce logging at ${t.salesforceCompliancePercent}%`
        : `${t.unresolvedSalesforceIssues} unresolved Salesforce issues`,
    );
  }

  const needsAttention = t.earlyWarningTriggered || t.paceStatus === "Slightly Behind";
  if (needsAttention && !behind) {
    for (const r of t.earlyWarningReasons.slice(0, 2)) reasons.push(r);
  }

  const status: TeamPlanStatus = behind
    ? "Behind Target"
    : overloaded
      ? "Overloaded"
      : dataQuality
        ? "Data Quality Issue"
        : needsAttention
          ? "Needs Attention"
          : "On Track";
  if (status === "On Track") reasons.unshift("All categories pacing at or above target");
  return { status, reasons };
}

export function buildTeamPlan(plStaffId: string): { rows: TeamPlanRow[]; summary: TeamPlanSummary } {
  const team = cceosSupervisedBy(plStaffId);
  const targetsById = new Map(staffTargetPerformance.map((t) => [t.staffId, t]));

  const rows: TeamPlanRow[] = [];
  for (const member of team) {
    const t = targetsById.get(member.staffId);
    if (!t) continue; // no target profile yet (staff not Active) — nothing to supervise
    const { status, reasons } = classify(t);
    const portfolio = portfolioForStaffId(member.staffId).counts;
    // Override completed/remaining with live store counts so the PL
    // dashboard reflects what the CCEO actually scheduled + completed
    // this month, not the static team-targets-mock snapshot. Falls
    // back to the mock value if no live activities exist yet (the
    // CCEO is genuinely idle for the month).
    const live = liveMonthCounts(member.staffId);
    const completedLive = live.completed > 0 ? live.completed : t.completedActivities;
    const remainingLive = Math.max(0, t.monthlyTargetActivities - completedLive);
    const achievementLive = t.monthlyTargetActivities > 0
      ? Math.round((completedLive / t.monthlyTargetActivities) * 100)
      : t.achievementPercent;
    rows.push({
      staffId: member.staffId,
      name: t.staffName,
      initials: t.initials,
      region: t.region,
      status,
      statusReasons: reasons,
      monthlyTarget: t.monthlyTargetActivities,
      completedThisMonth: completedLive,
      remainingThisMonth: remainingLive,
      weeklyPaceNeeded: Math.ceil(remainingLive / 4),
      achievementPercent: achievementLive,
      paceStatus: t.paceStatus,
      portfolio: {
        total: portfolio.total,
        client: portfolio.client,
        core: portfolio.core,
        missingSsa: portfolio.missingSsa,
        unclustered: portfolio.unclustered,
        partnerAssigned: portfolio.partnerAssigned,
      },
      categories: {
        visits: t.targetCategoryProgress.validVisits,
        trainings: t.targetCategoryProgress.trainingsCompleted,
        ssa: t.targetCategoryProgress.ssaCompletion,
        salesforce: t.targetCategoryProgress.salesforceLogging,
        corePackage: t.targetCategoryProgress.coreSchoolTargets,
      },
      salesforceCompliancePercent: t.salesforceCompliancePercent,
      unresolvedSalesforceIssues: t.unresolvedSalesforceIssues,
      fundingDelayDays: t.fundingDelayDays,
      blockedPlanningDays: t.blockedPlanningDays,
      partnerDependencyBlocks: t.partnerDependencyBlocks,
      approvedLeaveDays: t.approvedLeaveDays,
      recommendedSupportActions: t.recommendedSupportActions,
    });
  }

  rows.sort(
    (a, b) =>
      STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) ||
      a.achievementPercent - b.achievementPercent,
  );

  const byStatus = {
    "On Track": 0,
    "Needs Attention": 0,
    "Behind Target": 0,
    "Overloaded": 0,
    "Data Quality Issue": 0,
  } as Record<TeamPlanStatus, number>;
  for (const r of rows) byStatus[r.status] += 1;

  return {
    rows,
    summary: {
      cceos: rows.length,
      byStatus,
      schoolsMissingSsa: rows.reduce((a, r) => a + r.portfolio.missingSsa, 0),
      schoolsUnclustered: rows.reduce((a, r) => a + r.portfolio.unclustered, 0),
      totalRemainingThisMonth: rows.reduce((a, r) => a + r.remainingThisMonth, 0),
    },
  };
}
