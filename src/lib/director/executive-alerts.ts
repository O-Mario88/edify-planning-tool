// Executive alerts — the Country Director's "what needs my decision today"
// feed. Every alert is a country-level executive issue (money, mission,
// people, partners, risk) with the why and a recommended action attached,
// so the CD can act without dropping into operational pages.
//
// The engine derives alerts from the same sources the rest of the director
// dashboard reads (fund queue, operational risk backlog, staff/partner
// target performance, priority schools). When the backend lands, this file
// is the single seam to swap: GET /api/cd/executive-alerts returns the same
// ExecutiveAlert shape.

import {
  pendingFundRequests,
  fundedNotCompleted,
  operationalRisks,
  priorityDirectorSchools,
} from "@/lib/director-mock";
import {
  staffTargetPerformance,
  partnerTargetPerformance,
} from "@/lib/team-targets-mock";

export type ExecutiveAlertSeverity = "urgent" | "warning" | "watch";

export type ExecutiveAlert = {
  id: string;
  severity: ExecutiveAlertSeverity;
  /** What is wrong, in one executive sentence. */
  issue: string;
  /** Why it matters to the country mission / money / donor readiness. */
  why: string;
  /** Affected region / district / team. */
  scope: string;
  /** What the CD should do about it. */
  recommendedAction: string;
  actionLabel: string;
  actionHref: string;
};

const SEVERITY_RANK: Record<ExecutiveAlertSeverity, number> = {
  urgent: 0,
  warning: 1,
  watch: 2,
};

export type ExecutiveAlertInputs = {
  /** Schools not yet assigned to a cluster (from scopedClusterCounts). */
  unclusteredSchools?: number;
};

export function buildExecutiveAlerts(inputs: ExecutiveAlertInputs = {}): ExecutiveAlert[] {
  const alerts: ExecutiveAlert[] = [];

  // ── Money: fund requests waiting on the CD ─────────────────────────
  if (pendingFundRequests.length > 0) {
    const regions = pendingFundRequests.map((r) => r.region).join(", ");
    const activities = pendingFundRequests.reduce((a, r) => a + r.activitiesCovered, 0);
    alerts.push({
      id: "fund-requests-pending",
      severity: "urgent",
      issue: `${pendingFundRequests.length} regional fund requests are waiting for your review`,
      why: `They cover ${activities.toLocaleString()} planned activities — field teams cannot execute until funds are approved.`,
      scope: regions,
      recommendedAction: "Review each request against the approved monthly plan, then approve or return with a reason.",
      actionLabel: "Open Fund Approvals",
      actionHref: "/approvals",
    });
  }

  // ── Money: disbursed but not delivered ─────────────────────────────
  if (fundedNotCompleted.overdue > 0) {
    alerts.push({
      id: "funded-not-completed",
      severity: "warning",
      issue: `${fundedNotCompleted.overdue.toLocaleString()} funded activities are overdue with no completion recorded`,
      why: `${fundedNotCompleted.totalLabel} is parked in the field without delivery or accountability — a financial-control and donor-confidence risk.`,
      scope: "Country-wide",
      recommendedAction: "Ask Program Leads for an accountability sweep on overdue funded activities before the next disbursement cycle.",
      actionLabel: "View Finance Snapshot",
      actionHref: "#fund-approvals",
    });
  }

  // ── Risk backlog: lifted from the operational risk tiles ───────────
  const risk = (key: string) => operationalRisks.find((r) => r.key === key);
  const sf = risk("sf_overdue");
  if (sf) {
    alerts.push({
      id: "salesforce-backlog",
      severity: "warning",
      issue: `${sf.value} Salesforce records are overdue`,
      why: "Unlogged work is invisible to donors and breaks the verified-impact chain.",
      scope: "All teams",
      recommendedAction: "Have IA prioritise the verification backlog and PLs enforce same-week logging.",
      actionLabel: "Inspect Backlog",
      actionHref: "/quality-checks",
    });
  }
  const core = risk("core_behind");
  if (core) {
    alerts.push({
      id: "core-package-behind",
      severity: "warning",
      issue: `${core.value} core schools are behind on the support package`,
      why: "The core package (4 visits + 4 trainings) is the contract behind core-school impact claims.",
      scope: "Country-wide",
      recommendedAction: "Review core-school pacing with PLs and rebalance staff/partner delivery where capacity is the blocker.",
      actionLabel: "Open Core Analytics",
      actionHref: "/analytics",
    });
  }

  // ── People: staff at target risk ───────────────────────────────────
  const staffAtRisk = staffTargetPerformance.filter(
    (s) => s.paceStatus === "High Risk" || s.paceStatus === "Critical",
  );
  if (staffAtRisk.length > 0) {
    const regions = [...new Set(staffAtRisk.map((s) => s.region))].join(", ");
    alerts.push({
      id: "staff-target-risk",
      severity: staffAtRisk.some((s) => s.paceStatus === "Critical") ? "urgent" : "warning",
      issue: `${staffAtRisk.length} staff are at high or critical target risk`,
      why: "Sustained under-delivery puts country targets and donor commitments at risk — and may signal overload, not underperformance.",
      scope: regions || "Country-wide",
      recommendedAction: "Review the context flags (leave, funding delays, route difficulty) with PLs before any escalation; rebalance workload first.",
      actionLabel: "Open Staff Performance",
      actionHref: "/staff",
    });
  }

  // ── Partners: delivery / certification risk ────────────────────────
  const partnersAtRisk = partnerTargetPerformance.filter(
    (p) => p.risk === "High" || p.risk === "Critical",
  );
  if (partnersAtRisk.length > 0) {
    const worst = [...partnersAtRisk].sort((a, b) => a.achievementPercent - b.achievementPercent)[0];
    alerts.push({
      id: "partner-delivery-risk",
      severity: partnersAtRisk.some((p) => p.risk === "Critical") ? "urgent" : "warning",
      issue: `${partnersAtRisk.length} partners are at delivery risk (lowest: ${worst.partner} at ${worst.achievementPercent}%)`,
      why: "Partner-delivered schools lose support quality when a partner slips — and uncertified partners cannot carry assignment overflow.",
      scope: [...new Set(partnersAtRisk.map((p) => p.region))].join(", "),
      recommendedAction: "Review partner workload and certification status; pause new assignments to critical-risk partners.",
      actionLabel: "Open Partner Performance",
      actionHref: "/partners",
    });
  }

  // ── Schools: unsupported red-alert schools ─────────────────────────
  const redAlert = priorityDirectorSchools.filter((s) => s.risk === "High");
  if (redAlert.length > 0) {
    const regions = [...new Set(redAlert.map((s) => s.region))].join(", ");
    alerts.push({
      id: "red-alert-schools",
      severity: "warning",
      issue: `${redAlert.length} schools are on red alert (weak SSA, no recent visit or training)`,
      why: "Unsupported weak schools decline — they are the schools donor impact claims depend on improving.",
      scope: regions,
      recommendedAction: "Flag the relevant Program Lead to prioritise weak-SSA schools in their next planning cycle.",
      actionLabel: "Open SSA Analytics",
      actionHref: "/ssa",
    });
  }

  // ── Data quality: unclustered schools block planning ───────────────
  if ((inputs.unclusteredSchools ?? 0) > 0) {
    alerts.push({
      id: "unclustered-schools",
      severity: "watch",
      issue: `${inputs.unclusteredSchools} schools have no cluster assignment`,
      why: "The cluster gate blocks planning and cluster trainings for these schools until they are assigned.",
      scope: "Country-wide",
      recommendedAction: "Ask CCEOs/PLs to clear the cluster assignment queue.",
      actionLabel: "View Cluster Readiness",
      actionHref: "/analytics",
    });
  }

  return alerts.sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]);
}
