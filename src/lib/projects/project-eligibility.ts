// Project school eligibility (spec §6).
//
// A school is RECOMMENDED for a project when the gap the project targets is
// actually that school's weakness:
//   • its current SSA weakest (or near-weakest) intervention matches the
//     project's primary (or a secondary) intervention, AND
//   • it has a current SSA on record, AND
//   • it falls inside the project's geography scope (when scope is set).
//
// Recommendation is a steer, not a gate — users with permission may still
// assign any school manually (flag-not-block, mirroring cluster assignment).

import { intakeSchools, type IntakeSchool } from "@/lib/intake/intake-mock";
import type { SpecialProject } from "@/lib/special-projects-mock";
import { schoolProjectMemberships } from "@/lib/special-projects-mock";
import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";
import { SSA_INTERVENTIONS } from "@/lib/planning/ssa-performance-mock";
import { ssaForSchool, hasSsa } from "./project-school-ssa";

export type ProjectEligibility = {
  schoolId: string;
  schoolName: string;
  region: string;
  district: string;
  recommended: boolean;
  matchedOn?: "primary" | "secondary";
  matchedIntervention?: SsaInterventionArea;
  weakInterventionScore?: number;
  alreadyAssigned: boolean;
  reason: string;
};

function inScope(school: IntakeSchool, project: SpecialProject): boolean {
  const regions = project.scopeRegionIds;
  const districts = project.scopeDistrictIds;
  if (regions?.length && !regions.includes(school.region)) return false;
  if (districts?.length && !districts.includes(school.district)) return false;
  return true;
}

function isAssigned(schoolId: string, projectId: string): boolean {
  return schoolProjectMemberships.some(
    (m) => m.schoolId === schoolId && m.projectId === projectId && m.status === "Active",
  );
}

/** Rank of an intervention in a school's current SSA, 0 = weakest. */
function weaknessRank(schoolId: string, intervention: SsaInterventionArea): number | undefined {
  const r = ssaForSchool(schoolId);
  if (!r) return undefined;
  const sorted = [...SSA_INTERVENTIONS].sort((a, b) => r.current[a] - r.current[b]);
  return sorted.indexOf(intervention);
}

/**
 * Is this school recommended for this project? A school qualifies when the
 * project's primary intervention is among its weakest 3 areas, or a secondary
 * intervention is its single weakest area.
 */
export function evaluateEligibility(school: IntakeSchool, project: SpecialProject): ProjectEligibility {
  const base = {
    schoolId: school.schoolId,
    schoolName: school.schoolName,
    region: school.region,
    district: school.district,
    alreadyAssigned: isAssigned(school.schoolId, project.projectId),
  };

  if (!hasSsa(school.schoolId)) {
    return { ...base, recommended: false, reason: "No current SSA on record." };
  }
  if (!inScope(school, project)) {
    return { ...base, recommended: false, reason: "Outside the project's geography scope." };
  }

  const ssa = ssaForSchool(school.schoolId)!;
  const primaryRank = weaknessRank(school.schoolId, project.primaryInterventionId);
  if (primaryRank !== undefined && primaryRank <= 2) {
    return {
      ...base,
      recommended: true,
      matchedOn: "primary",
      matchedIntervention: project.primaryInterventionId,
      weakInterventionScore: ssa.current[project.primaryInterventionId],
      reason: `Weak in ${project.primaryInterventionId} (${ssa.current[project.primaryInterventionId]}/10) — the project's primary focus.`,
    };
  }
  for (const sec of project.secondaryInterventionIds ?? []) {
    const rank = weaknessRank(school.schoolId, sec);
    if (rank === 0) {
      return {
        ...base,
        recommended: true,
        matchedOn: "secondary",
        matchedIntervention: sec,
        weakInterventionScore: ssa.current[sec],
        reason: `Weakest area is ${sec} (${ssa.current[sec]}/10) — a secondary focus of the project.`,
      };
    }
  }
  return { ...base, recommended: false, reason: "SSA weakness does not match this project's interventions." };
}

/** Convenience for the directory drawer "Recommended" badge. */
export function isRecommendedForProject(schoolId: string, project: SpecialProject): boolean {
  const school = intakeSchools.find((s) => s.schoolId === schoolId);
  return school ? evaluateEligibility(school, project).recommended : false;
}

/**
 * All recommended-but-not-yet-assigned schools for a project, best matches
 * first. Pass a candidate list to limit scope (e.g. a CCEO's portfolio);
 * defaults to the whole directory.
 */
export function recommendSchoolsForProject(
  project: SpecialProject,
  candidates: IntakeSchool[] = intakeSchools,
): ProjectEligibility[] {
  return candidates
    .map((s) => evaluateEligibility(s, project))
    .filter((e) => e.recommended)
    .sort((a, b) => {
      if (a.alreadyAssigned !== b.alreadyAssigned) return a.alreadyAssigned ? 1 : -1;
      return (a.weakInterventionScore ?? 99) - (b.weakInterventionScore ?? 99);
    });
}
