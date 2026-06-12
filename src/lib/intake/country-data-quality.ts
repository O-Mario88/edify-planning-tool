// Country Data Quality Score (spec layer #10).
//
// For CD / IA / RVP: one confidence score that answers "how much do we trust our
// country data?" — composed from school master-data completeness AND workflow
// completeness (evidence, Salesforce IDs, IA verification, fund-cost match, the
// 10% QA sample). Produces a score, a band, and a plain-English risk summary
// ("86% — Good. Main risks: 10% QA incomplete, 42 schools missing prior-FY SSA").
//
// server-only: reads the Unified Activity model + fund requests.

import "server-only";

import { intakeSchools, ssaUploads } from "@/lib/intake/intake-mock";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { clusterStatusOf } from "@/lib/cluster/cluster-core";
import { allUnifiedActivities } from "@/lib/activity/unified-activity-source";
import type { UnifiedActivityStage } from "@/lib/activity/unified-activity";
import { fundRequests } from "@/lib/actions/store";
import { getClientVerificationProgress, } from "@/lib/verification/portfolio-verification-mock";
import { rollupPortfolioVerification } from "@/lib/verification/portfolio-verification";

export type DataQualityDimension = {
  key: string;
  label: string;
  ratio: number; // 0..1
  score: number; // 0..100
  detail: string;
  /** True when this dimension is dragging the score down (ratio < 0.8). */
  risk: boolean;
  weight: number;
};

export type CountryDataQualityBand = "Excellent" | "Good" | "Fair" | "Needs work";

export type CountryDataQualityReport = {
  generatedAt: string;
  score: number;
  band: CountryDataQualityBand;
  riskSummary: string;
  dimensions: DataQualityDimension[];
};

const DELIVERED: UnifiedActivityStage[] = [
  "evidence_pending", "salesforce_pending", "ia_pending", "ia_returned", "payment_pending", "closed",
];
const SUBMITTED: UnifiedActivityStage[] = ["ia_pending", "payment_pending", "closed"];

const ratio = (num: number, den: number) => (den === 0 ? 1 : num / den);

function bandFor(score: number): CountryDataQualityBand {
  if (score >= 90) return "Excellent";
  if (score >= 80) return "Good";
  if (score >= 70) return "Fair";
  return "Needs work";
}

export function countryDataQuality(): CountryDataQualityReport {
  const today = new Date().toISOString().slice(0, 10);
  const schools = intakeSchools;
  const n = schools.length;

  // ── School master-data completeness ──
  const withId = schools.filter((s) => !!s.schoolId).length;
  const withOwner = schools.filter((s) => resolveOwner(s.assignedCceo).status === "matched").length;
  const withCluster = schools.filter((s) => clusterStatusOf(s) === "clustered").length;
  const withCurrentSsa = schools.filter((s) => s.ssaStatus === "SSA Done").length;
  // Prior-FY SSA: a school with at least two uploads has a prior year to compare.
  const ssaCountBySchool = new Map<string, number>();
  for (const u of ssaUploads) ssaCountBySchool.set(u.schoolId, (ssaCountBySchool.get(u.schoolId) ?? 0) + 1);
  const withPriorSsa = schools.filter((s) => (ssaCountBySchool.get(s.schoolId) ?? 0) >= 2).length;

  // ── 10% QA sample completion ──
  const qa = rollupPortfolioVerification(getClientVerificationProgress());
  const qaRatio = qa.totalTarget > 0 ? Math.min(1, qa.totalVerified / qa.totalTarget) : 1;

  // ── Workflow completeness ──
  const acts = allUnifiedActivities();
  const delivered = acts.filter((a) => DELIVERED.includes(a.stage));
  const withEvidence = delivered.filter((a) => a.hasEvidence).length;
  const evidenced = delivered.filter((a) => a.hasEvidence);
  const withSf = evidenced.filter((a) => !!a.salesforceId).length;
  const submitted = acts.filter((a) => SUBMITTED.includes(a.stage));
  const iaConfirmed = submitted.filter((a) => a.iaStatus === "confirmed").length;
  const funds = fundRequests();
  const fundsMatched = funds.filter((r) => !r.risks?.includes("ExceedsApprovedWeeklyPlan")).length;

  const raw: Omit<DataQualityDimension, "score" | "risk">[] = [
    { key: "school_id", label: "Schools with School ID", ratio: ratio(withId, n), detail: `${withId}/${n}`, weight: 2 },
    { key: "owner", label: "Schools with account owner", ratio: ratio(withOwner, n), detail: `${withOwner}/${n}`, weight: 2 },
    { key: "cluster", label: "Schools assigned to a cluster", ratio: ratio(withCluster, n), detail: `${withCluster}/${n}`, weight: 2 },
    { key: "current_ssa", label: "Schools with current-FY SSA", ratio: ratio(withCurrentSsa, n), detail: `${withCurrentSsa}/${n}`, weight: 2 },
    { key: "prior_ssa", label: "Schools with prior-FY SSA", ratio: ratio(withPriorSsa, n), detail: `${withPriorSsa}/${n} (impact comparison needs two years)`, weight: 1 },
    { key: "qa_sample", label: "10% QA sample completed", ratio: qaRatio, detail: `${qa.totalVerified}/${qa.totalTarget} verified`, weight: 1 },
    { key: "evidence", label: "Delivered activities with evidence", ratio: ratio(withEvidence, delivered.length), detail: `${withEvidence}/${delivered.length}`, weight: 2 },
    { key: "salesforce", label: "Evidenced activities with Salesforce ID", ratio: ratio(withSf, evidenced.length), detail: `${withSf}/${evidenced.length}`, weight: 1 },
    { key: "ia", label: "Submitted activities IA-verified", ratio: ratio(iaConfirmed, submitted.length), detail: `${iaConfirmed}/${submitted.length}`, weight: 2 },
    { key: "fund_match", label: "Fund requests matching cost", ratio: ratio(fundsMatched, funds.length), detail: `${fundsMatched}/${funds.length}`, weight: 1 },
  ];

  const dimensions: DataQualityDimension[] = raw.map((d) => ({
    ...d,
    score: Math.round(d.ratio * 100),
    risk: d.ratio < 0.8,
  }));

  const totalWeight = dimensions.reduce((s, d) => s + d.weight, 0);
  const score = Math.round((dimensions.reduce((s, d) => s + d.ratio * d.weight, 0) / totalWeight) * 100);
  const band = bandFor(score);

  // Risk summary — the worst two or three dimensions, in plain English.
  const risks = dimensions
    .filter((d) => d.risk)
    .sort((a, b) => a.ratio - b.ratio)
    .slice(0, 3)
    .map((d) => `${d.label.toLowerCase()} (${d.detail})`);
  const riskSummary = risks.length
    ? `Main risks: ${risks.join("; ")}.`
    : "No major data-quality risks — every dimension is above 80%.";

  return { generatedAt: today, score, band, riskSummary, dimensions };
}
