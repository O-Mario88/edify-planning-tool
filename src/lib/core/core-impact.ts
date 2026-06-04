// Core impact engine — real baseline-vs-follow-up SSA comparison (mirrors the
// special-projects impact model). Computed from the plan's baseline snapshot
// and its follow-up SSA; returns per-intervention change + champion eligibility.

import "server-only";
import { SSA_INTERVENTION_AREAS, ssaAverage } from "@/lib/intake/intake-core";
import { planById, baselineSnapshot, followUpForPlan, interventionsForPlan } from "./core-store";
import {
  CHAMPION_SSA_THRESHOLD,
  type CoreImpactSnapshot,
  type InterventionChange,
  type ChangeClass,
  type SsaInterventionArea,
} from "./core-types";

function classify(change: number, hasBoth: boolean): ChangeClass {
  if (!hasBoth) return "No Comparison";
  if (change > 0.0001) return "Improved";
  if (change < -0.0001) return "Declined";
  return "No Change";
}

/** Compute the impact snapshot for a core plan, or undefined if no follow-up SSA. */
export function coreImpactFor(planId: string): CoreImpactSnapshot | undefined {
  const plan = planById(planId);
  if (!plan) return undefined;
  const baseline = baselineSnapshot(plan.baselineSSARecordId);
  const follow = followUpForPlan(planId);
  if (!baseline || !follow) return undefined;

  const priority = new Set(interventionsForPlan(planId).map((i) => i.intervention));

  const all: InterventionChange[] = SSA_INTERVENTION_AREAS.map((area) => {
    const b = baseline.scores[area];
    const f = follow.scores[area];
    const hasBoth = b != null && f != null;
    const change = hasBoth ? Math.round((f! - b!) * 10) / 10 : 0;
    return {
      intervention: area as SsaInterventionArea,
      baselineScore: b ?? 0,
      followUpScore: f ?? 0,
      change,
      classification: classify(change, hasBoth),
      priority: priority.has(area as SsaInterventionArea),
    };
  });

  const priorityChange = all.filter((c) => c.priority);
  const baselineAverage = baseline.average || ssaAverage(baseline.scores);
  const followUpAverage = follow.average || ssaAverage(follow.scores);
  const averageChange = Math.round((followUpAverage - baselineAverage) * 10) / 10;

  const improved = [...all].sort((a, b) => b.change - a.change);
  const bestImproved = improved[0]?.change > 0 ? improved[0].intervention : undefined;
  const weakestRemaining = [...all].sort((a, b) => a.followUpScore - b.followUpScore)[0]?.intervention;

  const impactStatus = averageChange > 0.0001 ? "Improved" : averageChange < -0.0001 ? "Declined" : "No Change";

  // Champion-eligible: strong follow-up average + every priority intervention improved.
  const championCandidate =
    followUpAverage >= CHAMPION_SSA_THRESHOLD &&
    priorityChange.length > 0 &&
    priorityChange.every((c) => c.change > 0);

  return {
    id: `cimpact-${planId}`,
    corePlanId: planId,
    schoolId: plan.schoolId,
    baselineSSARecordId: baseline.id,
    followUpSSARecordId: follow.id,
    baselineAverage,
    followUpAverage,
    averageChange,
    priorityInterventionChange: priorityChange,
    allInterventionChange: all,
    bestImproved,
    weakestRemaining,
    impactStatus,
    championCandidate,
    computedAt: new Date().toISOString(),
  };
}
