// Project impact (spec §14/§20) — the third layer of intelligence:
//   1. SSA intervention = what is weak
//   2. Project = what we are doing about it
//   3. Impact comparison = whether the project moved that weakness  ← here
//
// Two views:
//   • computeProjectImpact(projectId) — per-school before/after on the
//     project's MAPPED intervention, plus delivery reach from activities.
//   • projectVsNonProject(projectId)  — does the project cohort outperform
//     comparable non-project schools on the same intervention? (proves value)

import {
  projectById,
  schoolProjectMemberships,
  type SpecialProject,
} from "@/lib/special-projects-mock";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { trendFor, type SsaTrend } from "@/lib/planning/ssa-performance-mock";
import { ssaForSchool, scoredSchoolIds, weakestIntervention } from "./project-school-ssa";
import { activitiesForProjectSchool } from "./project-activities";

export type ImpactStatus = "Improved" | "Declined" | "No Change" | "Insufficient Data";

export type ProjectImpactSnapshot = {
  projectId: string;
  schoolId: string;
  schoolName: string;
  interventionScoreBefore?: number;
  interventionScoreAfter?: number;
  improvementValue?: number;
  trend?: SsaTrend;
  impactStatus: ImpactStatus;
  trained: boolean;
  followedUp: boolean;
  assessed: boolean;
};

export type ProjectImpact = {
  projectId: string;
  intervention: string;
  schoolsEnrolled: number;
  schoolsWithSsa: number;
  schoolsImproved: number;
  schoolsDeclined: number;
  schoolsFlat: number;
  avgImprovement: number; // on the mapped intervention, project schools
  avgBefore: number;
  avgAfter: number;
  schoolsTrained: number;
  schoolsFollowedUp: number;
  schoolsAssessed: number;
  perSchool: ProjectImpactSnapshot[];
};

function schoolName(schoolId: string): string {
  return intakeSchools.find((s) => s.schoolId === schoolId)?.schoolName ?? schoolId;
}

function statusFromChange(change?: number): ImpactStatus {
  if (change === undefined) return "Insufficient Data";
  if (change > 0) return "Improved";
  if (change < 0) return "Declined";
  return "No Change";
}

/** Active member schoolIds for a project. */
export function projectSchoolIds(projectId: string): string[] {
  return schoolProjectMemberships
    .filter((m) => m.projectId === projectId && m.status === "Active")
    .map((m) => m.schoolId);
}

export function computeProjectImpact(projectId: string): ProjectImpact | undefined {
  const project = projectById(projectId);
  if (!project) return undefined;
  const intervention = project.primaryInterventionId;
  const ids = projectSchoolIds(projectId);

  const perSchool: ProjectImpactSnapshot[] = ids.map((schoolId) => {
    const ssa = ssaForSchool(schoolId);
    const acts = activitiesForProjectSchool(projectId, schoolId);
    const trained = acts.some((a) => a.activityType === "Project Training" && a.status === "Completed");
    const followedUp = acts.some((a) => a.activityType === "Project Follow-Up Visit");
    const assessed = acts.some((a) => a.activityType === "Project Assessment");

    if (!ssa) {
      return {
        projectId, schoolId, schoolName: schoolName(schoolId),
        impactStatus: "Insufficient Data", trained, followedUp, assessed,
      };
    }
    const before = ssa.baseline[intervention];
    const after = ssa.current[intervention];
    const change = after - before;
    return {
      projectId, schoolId, schoolName: schoolName(schoolId),
      interventionScoreBefore: before,
      interventionScoreAfter: after,
      improvementValue: Math.round(change * 10) / 10,
      trend: trendFor(change),
      impactStatus: statusFromChange(change),
      trained, followedUp, assessed,
    };
  });

  const withSsa = perSchool.filter((p) => p.improvementValue !== undefined);
  const sum = (sel: (p: ProjectImpactSnapshot) => number) =>
    withSsa.reduce((a, p) => a + sel(p), 0);
  const n = withSsa.length || 1;

  return {
    projectId,
    intervention,
    schoolsEnrolled: ids.length,
    schoolsWithSsa: withSsa.length,
    schoolsImproved: perSchool.filter((p) => p.impactStatus === "Improved").length,
    schoolsDeclined: perSchool.filter((p) => p.impactStatus === "Declined").length,
    schoolsFlat: perSchool.filter((p) => p.impactStatus === "No Change").length,
    avgImprovement: Math.round((sum((p) => p.improvementValue ?? 0) / n) * 10) / 10,
    avgBefore: Math.round((sum((p) => p.interventionScoreBefore ?? 0) / n) * 10) / 10,
    avgAfter: Math.round((sum((p) => p.interventionScoreAfter ?? 0) / n) * 10) / 10,
    schoolsTrained: perSchool.filter((p) => p.trained).length,
    schoolsFollowedUp: perSchool.filter((p) => p.followedUp).length,
    schoolsAssessed: perSchool.filter((p) => p.assessed).length,
    perSchool,
  };
}

// ── Project vs. comparable non-project schools (spec §20) ──

export type CohortStat = {
  count: number;
  avgBefore: number;
  avgAfter: number;
  avgImprovement: number;
};

export type ProjectComparison = {
  projectId: string;
  intervention: string;
  project: CohortStat;
  nonProject: CohortStat;
  /** Difference in average improvement (project − non-project). */
  improvementGap: number;
};

function cohortStat(schoolIds: string[], intervention: SpecialProject["primaryInterventionId"]): CohortStat {
  const rows = schoolIds
    .map((id) => ssaForSchool(id))
    .filter((r): r is NonNullable<typeof r> => Boolean(r))
    .map((r) => ({ before: r.baseline[intervention], after: r.current[intervention] }));
  const n = rows.length || 1;
  const avgBefore = rows.reduce((a, r) => a + r.before, 0) / n;
  const avgAfter = rows.reduce((a, r) => a + r.after, 0) / n;
  return {
    count: rows.length,
    avgBefore: Math.round(avgBefore * 10) / 10,
    avgAfter: Math.round(avgAfter * 10) / 10,
    avgImprovement: Math.round((avgAfter - avgBefore) * 10) / 10,
  };
}

/**
 * Compare the project's schools against comparable NON-project schools — ones
 * whose own weakest area is the same intervention but that the project never
 * reached. This isolates the project's contribution.
 */
export function projectVsNonProject(projectId: string): ProjectComparison | undefined {
  const project = projectById(projectId);
  if (!project) return undefined;
  const intervention = project.primaryInterventionId;
  const inProject = new Set(projectSchoolIds(projectId));

  const comparable = scoredSchoolIds().filter((id) => {
    if (inProject.has(id)) return false;
    const weak = weakestIntervention(id);
    return weak?.intervention === intervention;
  });

  return {
    projectId,
    intervention,
    project: cohortStat([...inProject], intervention),
    nonProject: cohortStat(comparable, intervention),
    improvementGap:
      Math.round(
        (cohortStat([...inProject], intervention).avgImprovement -
          cohortStat(comparable, intervention).avgImprovement) * 10,
      ) / 10,
  };
}
