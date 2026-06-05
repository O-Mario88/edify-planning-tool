// Core School analytics — aggregates the unified lifecycle into the metrics and
// chart-ready series the spec (§20) calls for: lifecycle funnel, package
// completion, visits/trainings 1–4, follow-up completion, baseline-vs-follow-up
// improvement, staff-vs-partner delivery, intervention heatmap, champion counts.
// Role-scoped through coreBoardData; every number is derived from real records.

import "server-only";
import type { EdifyRole } from "@/lib/auth-public";
import { SSA_INTERVENTION_AREAS, type SsaInterventionArea } from "@/lib/intake/intake-core";
import { coreBoardData } from "./core-board";
import { coreCandidates } from "./core-candidates";
import { effectiveSchoolType } from "./core-store";

export type FunnelStage = { key: string; label: string; count: number };
export type SeqBar = { label: string; visits: number; trainings: number };
export type BeforeAfter = { schoolId: string; schoolName: string; baseline: number; followUp: number; change: number };
export type DeliverySplit = { staff: number; partner: number };
export type HeatRow = { schoolId: string; schoolName: string; scores: (number | null)[] };

export type CoreAnalytics = {
  scope: { plans: number };
  // Headline counts
  candidates: number;
  verified: number;
  onboarded: number;
  activePlans: number;
  packageComplete: number;
  followUpDone: number;
  championCandidates: number;
  verifiedChampions: number;
  avgPackagePercent: number;
  // Charts
  funnel: FunnelStage[];
  packageProgress: SeqBar;          // count completed at each of visit/training 1..4
  sequenceProgress: SeqBar[];       // per slot index 1..4
  beforeAfter: BeforeAfter[];
  priorityImprovement: { area: SsaInterventionArea; avgChange: number; schools: number }[];
  delivery: DeliverySplit;
  heatmap: { areas: readonly SsaInterventionArea[]; rows: HeatRow[] };
};

export function coreAnalytics(staffId: string, role: EdifyRole): CoreAnalytics {
  const cards = coreBoardData(staffId, role);

  // Lifecycle funnel — candidate pool is directory-derived (unscoped pipeline
  // view), the rest is scoped to the user's plans.
  const cand = coreCandidates();
  const candidates = cand.length;
  const verified = cand.filter((c) => c.candidateStatus === "Verified Potential Core").length
    + cards.length; // verified ones already promoted to plans still count as "passed verification"
  const onboarded = cards.length;
  const packageComplete = cards.filter((c) => c.progress.readyForFollowUpSSA || c.progress.totalCompleted >= 8).length;
  const followUpDone = cards.filter((c) => !!c.impact).length;
  const improved = cards.filter((c) => c.impact && c.impact.averageChange > 0).length;
  const championCandidates = cards.filter((c) => c.championStatus === "Potential Champion" || c.championStatus === "Under Review").length;
  const verifiedChampions = cards.filter((c) => c.championStatus === "Verified Champion").length;
  const activePlans = cards.filter((c) => c.plan.status === "Active" || c.plan.status === "In Progress").length;

  const funnel: FunnelStage[] = [
    { key: "candidate", label: "Candidate", count: candidates + onboarded },
    { key: "verified", label: "Verified", count: verified },
    { key: "onboarded", label: "Onboarded", count: onboarded },
    { key: "package", label: "4+4 Complete", count: packageComplete },
    { key: "followup", label: "Follow-Up SSA", count: followUpDone },
    { key: "improved", label: "Improved", count: improved },
    { key: "champion", label: "Champion", count: championCandidates + verifiedChampions },
  ];

  // Per-sequence completion (how many schools finished visit/training #n).
  const sequenceProgress: SeqBar[] = [1, 2, 3, 4].map((n) => {
    let visits = 0, trainings = 0;
    for (const c of cards) {
      for (const s of c.slots) {
        if (s.sequenceNumber !== n || s.status !== "Completed") continue;
        if (s.activityType === "visit") visits++; else trainings++;
      }
    }
    return { label: `#${n}`, visits, trainings };
  });
  const packageProgress: SeqBar = {
    label: "Package",
    visits: cards.reduce((s, c) => s + c.progress.visitsCompleted, 0),
    trainings: cards.reduce((s, c) => s + c.progress.trainingsCompleted, 0),
  };

  // Before/after on schools with an impact snapshot.
  const beforeAfter: BeforeAfter[] = cards
    .filter((c) => !!c.impact)
    .map((c) => ({
      schoolId: c.plan.schoolId,
      schoolName: c.schoolName,
      baseline: c.impact!.baselineAverage,
      followUp: c.impact!.followUpAverage,
      change: c.impact!.averageChange,
    }))
    .sort((a, b) => b.change - a.change);

  // Priority intervention improvement, averaged across schools with impact.
  const priorityAcc = new Map<SsaInterventionArea, { sum: number; n: number }>();
  for (const c of cards) {
    if (!c.impact) continue;
    for (const ch of c.impact.priorityInterventionChange) {
      const cur = priorityAcc.get(ch.intervention) ?? { sum: 0, n: 0 };
      cur.sum += ch.change; cur.n += 1;
      priorityAcc.set(ch.intervention, cur);
    }
  }
  const priorityImprovement = [...priorityAcc.entries()]
    .map(([area, v]) => ({ area, avgChange: Math.round((v.sum / v.n) * 10) / 10, schools: v.n }))
    .sort((a, b) => b.avgChange - a.avgChange);

  // Staff vs partner delivery (completed slots).
  let staff = 0, partner = 0;
  for (const c of cards) {
    for (const s of c.slots) {
      if (s.status !== "Completed") continue;
      if (s.assignedPartnerId || s.owner === "partner" || s.owner === "partner_facilitator") partner++;
      else staff++;
    }
  }

  // Intervention heatmap — latest known scores (follow-up if measured, else baseline).
  const heatRows: HeatRow[] = cards.map((c) => {
    const latest = c.impact?.allInterventionChange;
    const scores: (number | null)[] = SSA_INTERVENTION_AREAS.map((area) => {
      if (latest) {
        const m = latest.find((x) => x.intervention === area);
        return m ? (m.followUpScore || m.baselineScore) : null;
      }
      // No follow-up yet — use the baseline of any matching priority intervention.
      const iv = c.interventions.find((x) => x.intervention === area);
      return iv ? iv.baselineScore : null;
    });
    return { schoolId: c.plan.schoolId, schoolName: c.schoolName, scores };
  });

  const avgPackagePercent = cards.length
    ? Math.round(cards.reduce((s, c) => s + c.progress.packageCompletionPercent, 0) / cards.length)
    : 0;

  return {
    scope: { plans: cards.length },
    candidates, verified, onboarded, activePlans,
    packageComplete, followUpDone, championCandidates, verifiedChampions, avgPackagePercent,
    funnel,
    packageProgress,
    sequenceProgress,
    beforeAfter,
    priorityImprovement,
    delivery: { staff, partner },
    heatmap: { areas: SSA_INTERVENTION_AREAS, rows: heatRows },
  };
}

/** Tiny helper so callers needn't import effectiveSchoolType separately. */
export function isCoreSchool(schoolId: string): boolean {
  return effectiveSchoolType(schoolId) === "Core";
}
