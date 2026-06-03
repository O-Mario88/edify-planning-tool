// Onboarded schools → planner gaps.
//
// Bridges uploaded data into the plan-builder: each onboarded school
// (intake-mock `intakeSchools`) + its latest uploaded SSA (`ssaUploads`)
// becomes a SchoolGap the SchoolGapsBoard already knows how to render. This is
// what makes "the schools/SSA I uploaded actually drive planning" true.
//
// Two name-space bridges happen here:
//   • uploaded SSA area keys (intake wording) → planning SsaInterventionArea
//   • onboarded school's assignedCceo NAME → staffId (for supervision scoping)

import type { EdifyRole } from "@/lib/auth";
import { intakeSchools, ssaUploads } from "@/lib/intake/intake-mock";
import { clusterStatusOf } from "@/lib/cluster/cluster-core";
import { schoolWorkflowState } from "@/lib/school-directory/school-state";
import { staffIdByName, visibleStaffIds } from "@/lib/org/supervision";
import type { SchoolGap, SsaInterventionArea, SchoolGapCategory } from "./planning-gaps-mock";

// Uploaded SSA uses the field's wording; the planner uses the analytics wording.
const INTAKE_TO_PLANNING_AREA: Record<string, SsaInterventionArea> = {
  "Teaching Environment": "Teaching & Learning",
  "Fees/Budget and Accounts": "Financial Health",
  "Government Requirement": "Government Requirements & Compliance",
  "Leadership Best Practice": "Leadership",
  "Christlike Behaviour": "Christlike Behaviour",
  "Exposure to the Word of God": "Exposure to the Word of God",
  "Learning Environment": "Learning Environment",
  "Education Technology": "Education Technology",
};

function weakAreas(scores: Record<string, number>): { area: SsaInterventionArea; score: number }[] {
  return Object.entries(scores)
    .map(([k, v]) => ({ area: INTAKE_TO_PLANNING_AREA[k], score: Number(v) }))
    .filter((x): x is { area: SsaInterventionArea; score: number } => !!x.area && Number.isFinite(x.score))
    .sort((a, b) => a.score - b.score);
}

function latestUploadFor(schoolId: string) {
  return ssaUploads
    .filter((u) => u.schoolId === schoolId)
    .sort((a, b) => b.ssaDate.localeCompare(a.ssaDate))[0];
}

/** Every onboarded school as a planner SchoolGap (SSA-driven weak areas). */
export function onboardedSchoolGaps(): SchoolGap[] {
  return intakeSchools.map((s) => {
    const up = latestUploadFor(s.schoolId);
    const weak = up ? weakAreas(up.scores) : [];
    const done = s.ssaStatus === "SSA Done";
    const clustered = clusterStatusOf(s) === "clustered";
    const worst = weak[0]?.score;
    // Single source of truth: the canonical pipeline stage drives the gap.
    const stage = schoolWorkflowState(s).stage;
    const gapCategory: SchoolGapCategory =
      stage === "needs_owner" || stage === "unclustered" ? "no_cluster"
      : stage === "ssa_required" ? "no_ssa"
      : "no_training";
    const riskLevel: SchoolGap["riskLevel"] =
      gapCategory === "no_cluster" ? "High"
      : gapCategory === "no_ssa" ? "Critical"
      : worst == null ? "Medium"
      : worst <= 3 ? "Critical"
      : worst <= 5 ? "High"
      : worst <= 7 ? "Medium" : "Low";
    return {
      id: `onb-${s.schoolId}`,
      schoolName: s.schoolName,
      district: s.district,
      subCounty: s.subCounty ?? "",
      parish: s.parish,
      clusterName: s.cluster,
      assignedCceo: s.assignedCceo ?? "Unassigned",
      ssaCompleted: done,
      ssaDate: up?.ssaDate,
      weakestArea: weak[0],
      secondWeakArea: weak[1],
      inCluster: clustered,
      riskLevel,
      gapCategory,
    };
  });
}

/**
 * Scope a gap list to a viewer by the supervision chain (CCEO name → staffId).
 * CD / RVP / Admin see everything. A gap whose owner can't be resolved to a
 * known staffId is kept (never silently drop data we can't place).
 */
export function scopeGapsToViewer(gaps: SchoolGap[], viewerStaffId: string, viewerRole: EdifyRole): SchoolGap[] {
  if (viewerRole === "Admin" || viewerRole === "CountryDirector" || viewerRole === "RVP") return gaps;
  const scope = visibleStaffIds(viewerStaffId, viewerRole);
  return gaps.filter((g) => {
    const id = staffIdByName(g.assignedCceo);
    return id ? scope.has(id) : true;
  });
}
