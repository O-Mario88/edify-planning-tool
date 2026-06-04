// Core board projection — scoped CorePlan cards for the planning board + the
// core directory. Reads the unified store (no hardcoded plans). Role-scoped:
// CCEO/PL see their directory schools; broader roles see all.

import "server-only";
import type { EdifyRole } from "@/lib/auth-public";
import { directoryRecords } from "@/lib/school-directory/directory";
import { intakeSchools } from "@/lib/intake/intake-mock";
import {
  corePlans, slotsForPlan, interventionsForPlan, profileFor,
} from "./core-store";
import { corePlanProgress, type CorePlanProgress } from "./core-progress";
import { coreImpactFor } from "./core-impact";
import type {
  CorePlan, CoreActivitySlot, CorePlanIntervention, CoreImpactSnapshot, ChampionStatus,
} from "./core-types";

export type CorePlanCardVM = {
  plan: CorePlan;
  schoolName: string;
  district: string;
  cluster?: string;
  owner?: string;
  baselineAverage: number;
  championStatus: ChampionStatus;
  progress: CorePlanProgress;
  interventions: CorePlanIntervention[];
  slots: CoreActivitySlot[];
  impact?: CoreImpactSnapshot;
};

function scopeIds(staffId: string, role: EdifyRole): Set<string> | "all" {
  if (role === "CCEO" || role === "CountryProgramLead") {
    return new Set(directoryRecords(staffId, role).map((s) => s.schoolId));
  }
  return "all";
}

export function coreBoardData(staffId: string, role: EdifyRole): CorePlanCardVM[] {
  const ids = scopeIds(staffId, role);
  return corePlans()
    .filter((p) => ids === "all" || ids.has(p.schoolId))
    .map((p) => {
      const school = intakeSchools.find((s) => s.schoolId === p.schoolId);
      const profile = profileFor(p.schoolId);
      return {
        plan: p,
        schoolName: school?.schoolName ?? p.schoolId,
        district: school?.district ?? "—",
        cluster: school?.cluster,
        owner: school?.assignedCceo,
        baselineAverage: p.packageCompletionPercent >= 0 ? (impactBaseline(p) ?? 0) : 0,
        championStatus: profile?.championStatus ?? "Not Eligible",
        progress: corePlanProgress(p.id),
        interventions: interventionsForPlan(p.id),
        slots: slotsForPlan(p.id),
        impact: coreImpactFor(p.id),
      };
    })
    .sort((a, b) => b.progress.packageCompletionPercent - a.progress.packageCompletionPercent);
}

function impactBaseline(p: CorePlan): number | undefined {
  // baseline average lives on the snapshot referenced by the plan.
  const interventions = interventionsForPlan(p.id);
  if (interventions.length === 0) return undefined;
  return Math.round((interventions.reduce((s, i) => s + i.baselineScore, 0) / interventions.length) * 10) / 10;
}

export function coreBoardSummary(cards: CorePlanCardVM[]) {
  return {
    plans: cards.length,
    active: cards.filter((c) => c.plan.status === "Active" || c.plan.status === "In Progress").length,
    pendingFollowUp: cards.filter((c) => c.plan.status === "Completed Pending Follow-Up SSA").length,
    impactMeasured: cards.filter((c) => !!c.impact).length,
    champions: cards.filter((c) => c.championStatus !== "Not Eligible").length,
    visitsDone: cards.reduce((s, c) => s + c.progress.visitsCompleted, 0),
    trainingsDone: cards.reduce((s, c) => s + c.progress.trainingsCompleted, 0),
  };
}
