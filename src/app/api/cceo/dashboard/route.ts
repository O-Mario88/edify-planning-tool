// GET /api/cceo/dashboard — one composition read for the CCEO command
// center: top-5 today actions, planning red-alert count, SSA-missing count,
// partner-work bucket counts, evidence-queue counts, current-week fund
// summary, and the cumulative target snapshot. Imports the SAME shared
// engines as the dedicated /api/cceo/* routes (no internal HTTP fetches).
// ?fy=/?week=/?month= are ignored (each block is current-period by design).

import type { NextRequest } from "next/server";
import { requireCceo, ok, type NextAction } from "../_auth";
import { toCurrentUser } from "@/lib/auth";
import { buildRoleActionBoard } from "@/lib/actions/role-action-engine";
import { directoryRecords } from "@/lib/school-directory/directory";
import { onboardedSchoolGaps, scopeGapsToViewer } from "@/lib/planning/onboarded-gaps";
import { backendSchoolGaps } from "@/lib/planning/backend-school-gaps";
import { backendClusterGaps } from "@/lib/planning/backend-cluster-gaps";
import { engineClusterGaps } from "@/lib/planning/engine-cluster-gaps";
import { assignedGapIds } from "@/lib/planning/assignment-overlay";
import { resolveCoreBoardData } from "@/lib/core/core-board";
import { computeProjectPlanningGaps } from "@/lib/projects/project-planning-gaps";
import { buildPlanningCategories } from "@/lib/planning/planning-categories";
import { loadVisitCostRates, loadGroupActivityRates } from "@/lib/cost-engine/cost-engine-server";
import { buildPartnerWork } from "@/lib/cceo/partner-work";
import { buildEvidenceQueues } from "@/lib/cceo/evidence-queues";
import { findRequestsForStaff, currentWeek } from "@/lib/funds/weekly-fund-mock";
import { computePeriodTarget } from "@/lib/targets/period-target";
import { portfolioForStaffId } from "@/lib/portfolio/portfolio";
import { schoolIdsWithActivePartner } from "@/lib/portfolio/partner-assignments";
import { deriveQuarterFromDate } from "@/lib/intake/intake-core";
import { engineNowIso } from "@/lib/clock";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  // 1 · Today actions (top 5 = next-3 + the rest of the inbox by priority).
  const board = buildRoleActionBoard({
    role: user.role,
    name: user.name,
    email: user.email,
    cookieHeader: req.headers.get("cookie"),
  });
  const topIds = new Set(board.nextThree.map((a) => a.id));
  const todayActions = [
    ...board.nextThree,
    ...board.inbox.filter((a) => !topIds.has(a.id)).sort((a, b) => a.priority - b.priority),
  ].slice(0, 5);

  // 2 · Planning categories → red-alert count (same derivation as
  //     /api/cceo/planning-gaps: backend-first, mock fallback).
  const beGaps = await backendSchoolGaps(user);
  const assigned = assignedGapIds();
  const schoolGaps =
    beGaps ??
    scopeGapsToViewer(onboardedSchoolGaps(), user.staffId, user.role).filter(
      (x) => !assigned.has(x.id),
    );
  const clusterGaps = (await backendClusterGaps(user)) ?? engineClusterGaps();
  const schools = directoryRecords(user.staffId, user.role);
  const projectGaps = computeProjectPlanningGaps(
    toCurrentUser(user),
    user.role === "CCEO" ? new Set(schools.map((s) => s.schoolId)) : "all",
  );
  const coreCards = await resolveCoreBoardData(
    { email: user.email, role: user.role },
    user.staffId,
    user.role,
  );
  const categories = buildPlanningCategories({
    schoolGaps,
    clusterGaps,
    coreCards,
    projectGaps,
    rates: { visit: loadVisitCostRates(), group: loadGroupActivityRates() },
  });
  const redAlertCount = categories.reduce((n, c) => n + c.redAlertCount, 0);

  // 3 · SSA-missing count over the viewer's directory.
  const ssaMissingCount = schools.filter((s) => s.ssaStatus !== "SSA Done").length;

  // 4 · Partner-work bucket counts.
  const pw = buildPartnerWork({ name: user.name, role: user.role, staffId: user.staffId });
  const partnerWork = {
    totalOpen: pw.totalOpen,
    urgentCount: pw.urgent.length,
    buckets: pw.buckets.map((b) => ({ key: b.key, label: b.label, count: b.count, tone: b.tone })),
    paymentPipeline: { count: pw.payment.count, totalUgx: pw.payment.totalUgx },
  };

  // 5 · Evidence-queue counts.
  const evidenceQueue = buildEvidenceQueues({ staffId: user.staffId }).counts;

  // 6 · Current-week fund request summary.
  const requests = findRequestsForStaff(user.staffId);
  const current = requests.find((r) => r.period.weekOfMonth === currentWeek.weekOfMonth);
  const fundRequest = {
    week: currentWeek.weekOfMonth,
    monthLabel: currentWeek.monthLabel,
    daysRemaining: currentWeek.daysRemaining,
    status: current?.status ?? null,
    requestedUgx: current?.requestedAmount.amount ?? 0,
    openRequests: requests.filter((r) => r.status !== "CLOSED" && r.status !== "ARCHIVED").length,
  };

  // 7 · Cumulative target snapshot (portfolio coverage, current quarter).
  const portfolio = portfolioForStaffId(user.staffId);
  const withPartner = schoolIdsWithActivePartner();
  const supported = portfolio.schools.filter(
    (s) => s.ssaStatus === "SSA Done" || withPartner.has(s.schoolId),
  ).length;
  const targetSnapshot = computePeriodTarget({
    fyTarget: portfolio.schools.length,
    achieved: supported,
    selectedQuarter: deriveQuarterFromDate(engineNowIso()),
  });

  const nextActions: NextAction[] = todayActions.slice(0, 3).map((a) => ({
    label: a.title,
    reason: a.description,
    href: a.primaryAction.href ?? "/dashboard",
  }));

  return ok(
    {
      header: board.header,
      todayActions,
      redAlertCount,
      ssaMissingCount,
      partnerWork,
      evidenceQueue,
      fundRequest,
      targetSnapshot,
    },
    nextActions,
  );
}
