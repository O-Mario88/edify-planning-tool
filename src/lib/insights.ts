// System-generated insight engine.
//
// Produces "what the system is noticing" cards for each role's dashboard.
// Insights are derived from already-seeded mock data so they read as live
// observations rather than hand-curated copy.

import "server-only";
import { type Insight } from "@/components/insights/InsightCard";
import { monthlyPlanSubmissions, monthlyApprovalKpis } from "@/lib/monthly-approval-mock";
import { formatUgxBig, validateCountryCostSettings } from "@/lib/cost-settings-mock";
import { planningDataReadiness } from "@/lib/data-intake-mock";
import { schoolFinancialYearSummaries } from "@/lib/fy-engine";
import { districtSsaComparison, generateSsaImprovementInsights } from "@/lib/ssa-comparison-mock";
import { coverageKpis, cceoCoverageRows } from "@/lib/coverage-mock";

// ────────── Country Director insights ──────────

export function insightsForCountryDirector(): Insight[] {
  const out: Insight[] = [];
  const k = monthlyApprovalKpis();
  const cs = validateCountryCostSettings();
  const r  = planningDataReadiness();
  const ssaInsights = generateSsaImprovementInsights();

  // Funding gap intelligence — name the driver region.
  if (k.fundingGap > 0) {
    const overGapSubs = monthlyPlanSubmissions.filter((s) => s.fundingGap > 0);
    const driver = [...overGapSubs].sort((a, b) => b.fundingGap - a.fundingGap)[0];
    if (driver) {
      out.push({
        id: "cd-funding-gap",
        tone: "warning",
        headline: `Funding gap is mainly driven by ${driver.region} Region`,
        body: `${driver.programLeadName}'s ${driver.monthLabel} request leaves a ${formatUgxBig(driver.fundingGap)} gap. ${driver.activities.filter((a) => a.corePackage).length} Core 4+4 activities are inside this gap.`,
        ctaLabel: "Open Funds Matching",
        ctaHref: "/budget/approvals/funds-matching",
      });
    }
  }

  // CD-approvable queue.
  const pendingCdCount = monthlyPlanSubmissions.filter(
    (s) => s.status === "Submitted to Country Director" || s.status === "Approved by Program Lead",
  ).length;
  if (pendingCdCount > 0) {
    out.push({
      id: "cd-queue",
      tone: "info",
      headline: `${pendingCdCount} PL submission${pendingCdCount === 1 ? "" : "s"} need your review`,
      body: `Each carries an active accountant note + available funds source. Open the dashboard to triage by priority.`,
      ctaLabel: "Open Approvals",
      ctaHref: "/approvals",
    });
  }

  // Cost settings risk.
  if (!cs.ready) {
    out.push({
      id: "cd-cost-settings",
      tone: "warning",
      headline: `${cs.missing.length} cost settings still in Draft`,
      body: "Final budget approval is BLOCKED until these are activated. Most affect Cluster Training + Evidence Verification rates for this FY.",
      ctaLabel: "Activate cost settings",
      ctaHref: "/cost-settings",
    });
  }

  // SSA improvement headline.
  const topSsa = ssaInsights.find((i) => i.kind === "most-improved-district");
  if (topSsa) {
    out.push({
      id: "cd-ssa-improvement",
      tone: "success",
      headline: topSsa.headline,
      body: topSsa.detail,
      ctaLabel: "Open SSA comparison",
      ctaHref: "/fy/ssa-comparison",
    });
  }

  // Repeated weakness pattern.
  const weakness = ssaInsights.find((i) => i.kind === "repeated-weakness");
  if (weakness) {
    out.push({
      id: "cd-weakness",
      tone: "highlight",
      headline: weakness.headline,
      body: weakness.detail,
      ctaLabel: "Open SSA comparison",
      ctaHref: "/fy/ssa-comparison",
    });
  }

  // Data readiness blocker.
  if (r.overall === "Blocked") {
    out.push({
      id: "cd-data-readiness",
      tone: "warning",
      headline: `Planning data has ${r.blockingIssues.length} blocking issue${r.blockingIssues.length === 1 ? "" : "s"}`,
      body: r.blockingIssues[0] ?? "Open the Planning Data Readiness page for details.",
      ctaLabel: "Open Readiness",
      ctaHref: "/data-intake/readiness",
    });
  }

  // Coverage — unassigned schools + at-risk CCEOs
  const cov = coverageKpis();
  if (cov.unassigned > 0) {
    out.push({
      id: "cd-coverage-unassigned",
      tone: "warning",
      headline: `${cov.unassigned.toLocaleString()} client schools still unassigned`,
      body: `Staff capacity covers ${cov.cceoCoveragePct}% directly. Partners cover ${cov.partnerCoveragePct}%. The remaining schools need partner matches — system has ranked them by SSA risk.`,
      ctaLabel: "Open partner recommendations",
      ctaHref: "/coverage/recommendations",
    });
  }
  const cceosAtRisk = cceoCoverageRows.filter((c) => c.status === "Critical" || c.status === "High Risk");
  if (cceosAtRisk.length > 0) {
    out.push({
      id: "cd-cceo-at-risk",
      tone: "warning",
      headline: `${cceosAtRisk.length} CCEO${cceosAtRisk.length === 1 ? " is" : "s are"} behind on annual visit target`,
      body: `${cceosAtRisk[0].staffName} is at ${cceosAtRisk[0].monthlyPacePct}% pace (avg ${cceosAtRisk[0].dailyAvgLast14.toFixed(1)} visits/day). Daily compliance: ${cceosAtRisk[0].dailyCompliancePct}%.`,
      ctaLabel: "Open Coverage dashboard",
      ctaHref: "/coverage",
    });
  }

  return out.slice(0, 6);
}

// ────────── CPL insights ──────────

export function insightsForCpl(): Insight[] {
  const out: Insight[] = [];

  // My pending review queue (PL stage).
  const myQueue = monthlyPlanSubmissions.filter((s) => s.status === "Submitted to Program Lead");
  if (myQueue.length > 0) {
    out.push({
      id: "cpl-queue",
      tone: "info",
      headline: `${myQueue.length} monthly plan${myQueue.length === 1 ? "" : "s"} awaiting your review`,
      body: "Check workload realism, SSA-informed prioritisation, and Core 4+4 alignment before submitting up.",
      ctaLabel: "Open submissions",
      ctaHref: "/approvals",
    });
  }

  // Gateway not done.
  const gatewayPending = schoolFinancialYearSummaries.filter(
    (s) => s.gatewayStatus === "Gateway Required" || s.gatewayStatus === "Gateway Scheduled",
  ).length;
  if (gatewayPending > 0) {
    out.push({
      id: "cpl-gateway",
      tone: "warning",
      headline: `${gatewayPending} schools have not completed Gateway Training`,
      body: "SSA cannot become due until Gateway is complete. Confirm cluster names + dates this week.",
      ctaLabel: "Open Gateway",
      ctaHref: "/fy/gateway",
    });
  }

  // SSA verification.
  const ssaPending = schoolFinancialYearSummaries.filter((s) => s.ssaCompleted && !s.ssaVerified).length;
  if (ssaPending > 0) {
    out.push({
      id: "cpl-ssa-verify",
      tone: "highlight",
      headline: `${ssaPending} SSAs done but not verified`,
      body: "Verified SSA unlocks Full Planning Mode + Core onboarding. Verification is the gateway, not paperwork.",
      ctaLabel: "Verification Queue",
      ctaHref: "/queue",
    });
  }

  return out.slice(0, 4);
}

// ────────── RVP insights ──────────

export function insightsForRvp(): Insight[] {
  const out: Insight[] = [];
  const queue = monthlyPlanSubmissions.filter((s) => s.status === "Submitted to RVP");
  if (queue.length > 0) {
    const total = queue.reduce((a, s) => a + (s.amendedBudget ?? s.requestedBudget), 0);
    out.push({
      id: "rvp-queue",
      tone: "info",
      headline: `${queue.length} CD-approved submission${queue.length === 1 ? "" : "s"} awaiting final approval`,
      body: `Combined value: ${formatUgxBig(total)}. Each carries a complete amendment audit + decision-impact context.`,
      ctaLabel: "Open RVP queue",
      ctaHref: "/budget/approvals/rvp-queue",
    });
  }

  // District-level country risk.
  const declining = districtSsaComparison.filter((d) => d.status === "Declining");
  if (declining.length > 0) {
    out.push({
      id: "rvp-declining",
      tone: "warning",
      headline: `${declining.length} district${declining.length === 1 ? "" : "s"} declining on SSA`,
      body: `${declining[0].district} is the steepest drop (${declining[0].change.toFixed(1)} pts). Weakest intervention: ${declining[0].weakestIntervention}.`,
      ctaLabel: "Open SSA comparison",
      ctaHref: "/fy/ssa-comparison",
    });
  }

  return out.slice(0, 3);
}

// ────────── Impact Assessment insights ──────────

export function insightsForImpactAssessment(): Insight[] {
  const out: Insight[] = [];
  const r = planningDataReadiness();

  const blocked = r.rows.filter((x) => x.status === "Blocked");
  if (blocked.length > 0) {
    out.push({
      id: "ia-blocked",
      tone: "warning",
      headline: `${blocked.length} data area${blocked.length === 1 ? "" : "s"} blocked`,
      body: `${blocked[0].area} — ${blocked[0].note}. Resolve before the planning engine can consume new data.`,
      ctaLabel: "Open Readiness",
      ctaHref: "/data-intake/readiness",
    });
  }

  // SSAs ready vs scheduled.
  const needsAttention = r.rows.filter((x) => x.status === "Needs Attention");
  if (needsAttention.length > 0) {
    out.push({
      id: "ia-attention",
      tone: "info",
      headline: `${needsAttention.length} area${needsAttention.length === 1 ? "" : "s"} need attention`,
      body: needsAttention.map((x) => x.area).join(" · "),
      ctaLabel: "Open Queue",
      ctaHref: "/data-intake/queue",
    });
  }

  // Repeated weakness insight pulled from SSA.
  const weakness = generateSsaImprovementInsights().find((i) => i.kind === "repeated-weakness");
  if (weakness) {
    out.push({
      id: "ia-weakness",
      tone: "highlight",
      headline: weakness.headline,
      body: weakness.detail,
      ctaLabel: "Open SSA comparison",
      ctaHref: "/fy/ssa-comparison",
    });
  }

  return out.slice(0, 4);
}
