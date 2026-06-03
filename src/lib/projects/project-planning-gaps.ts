// Project planning-gap lists (spec §17) for the CCEO/PL planning page.
//
// These are the project-specific "what needs doing next" queues, derived from
// each project school's activity + SSA state. They never replace the SSA gap
// boards — they sit alongside them so a CCEO/PL sees their project follow-up
// work in the same place as their core planning.

import { getVisibleProjects, schoolProjectMemberships } from "@/lib/special-projects-mock";
import type { CurrentUser } from "@/lib/schools-mock";
import { intakeSchools, type IntakeSchool } from "@/lib/intake/intake-mock";
import { activitiesForProjectSchool, type ProjectActivity } from "./project-activities";
import { ssaForSchool } from "./project-school-ssa";

export type ProjectGapItem = {
  key: string; // projectId:schoolId
  projectId: string;
  projectShortName: string;
  schoolId: string;
  schoolName: string;
  district: string;
  intervention: string;
  detail: string;
  href: string;
};

export type ProjectGapCategoryKey =
  | "notYetTrained"
  | "needingFollowUp"
  | "partnerAssignedNotScheduled"
  | "evidenceMissing"
  | "salesforceIdMissing"
  | "iaVerificationPending"
  | "dueForAssessment"
  | "noImprovement";

export type ProjectGapCategory = {
  key: ProjectGapCategoryKey;
  label: string;
  action: string;
  items: ProjectGapItem[];
};

const CATEGORY_META: { key: ProjectGapCategoryKey; label: string; action: string }[] = [
  { key: "notYetTrained",               label: "Project Schools Not Yet Trained",        action: "Schedule training" },
  { key: "needingFollowUp",             label: "Project Schools Needing Follow-Up",      action: "Schedule follow-up" },
  { key: "partnerAssignedNotScheduled", label: "Partner Activities Not Yet Scheduled",   action: "Chase partner" },
  { key: "evidenceMissing",             label: "Project Evidence Missing",               action: "Upload / accept evidence" },
  { key: "salesforceIdMissing",         label: "Project Salesforce ID Missing",          action: "Enter Salesforce ID" },
  { key: "iaVerificationPending",       label: "Project IA Verification Pending",        action: "Await IA" },
  { key: "dueForAssessment",            label: "Project Schools Due for Assessment",     action: "Schedule assessment" },
  { key: "noImprovement",               label: "Project Schools Showing No Improvement", action: "Re-plan support" },
];

const completed = (a: ProjectActivity) => a.status === "Completed";

export function computeProjectPlanningGaps(
  currentUser: CurrentUser,
  scopedSchoolIds: Set<string> | "all",
): ProjectGapCategory[] {
  const buckets: Record<ProjectGapCategoryKey, ProjectGapItem[]> = {
    notYetTrained: [], needingFollowUp: [], partnerAssignedNotScheduled: [],
    evidenceMissing: [], salesforceIdMissing: [], iaVerificationPending: [],
    dueForAssessment: [], noImprovement: [],
  };

  for (const project of getVisibleProjects(currentUser)) {
    const memberIds = schoolProjectMemberships
      .filter((m) => m.projectId === project.projectId && m.status === "Active")
      .map((m) => m.schoolId)
      .filter((id) => scopedSchoolIds === "all" || scopedSchoolIds.has(id));

    for (const schoolId of memberIds) {
      const school: IntakeSchool | undefined = intakeSchools.find((s) => s.schoolId === schoolId);
      if (!school) continue;
      const acts = activitiesForProjectSchool(project.projectId, schoolId);
      const base = {
        key: `${project.projectId}:${schoolId}`,
        projectId: project.projectId,
        projectShortName: project.projectShortName,
        schoolId,
        schoolName: school.schoolName,
        district: school.district,
        intervention: project.primaryInterventionId,
        href: `/projects/${project.projectId}`,
      };
      const push = (k: ProjectGapCategoryKey, detail: string, href = base.href) =>
        buckets[k].push({ ...base, detail, href });

      const trained = acts.some((a) => a.activityType === "Project Training" && completed(a));
      const followed = acts.some((a) => a.activityType === "Project Follow-Up Visit" && completed(a));
      const assessed = acts.some((a) => a.activityType === "Project Assessment" && completed(a));
      const completedActs = acts.filter(completed);

      if (!trained) push("notYetTrained", `No completed training yet · ${project.primaryInterventionId}`);
      else if (!followed) push("needingFollowUp", "Trained — follow-up visit outstanding");

      if (acts.some((a) => a.workflowStatus === "AssignedToPartner"))
        push("partnerAssignedNotScheduled", "Assigned to partner, awaiting schedule", "/special-projects/pipeline");

      if (completedActs.some((a) => a.evidenceStatus === "Pending" || a.evidenceStatus === "Submitted" || a.evidenceStatus === "Returned"))
        push("evidenceMissing", "Completed activity without verified evidence", "/special-projects/pipeline");

      if (completedActs.some((a) => !a.salesforceActivityId))
        push("salesforceIdMissing", "Completed activity missing Salesforce ID", "/special-projects/pipeline");

      if (acts.some((a) => a.workflowStatus === "SubmittedToIA" || (completed(a) && a.iaVerificationStatus === "Submitted")))
        push("iaVerificationPending", "Submitted — awaiting IA confirmation", "/special-projects/pipeline");

      if (trained && followed && !assessed)
        push("dueForAssessment", "Trained + followed up — assessment due");

      const ssa = ssaForSchool(schoolId);
      if (ssa && ssa.current[project.primaryInterventionId] <= ssa.baseline[project.primaryInterventionId])
        push("noImprovement", `No gain on ${project.primaryInterventionId} (${ssa.baseline[project.primaryInterventionId]} → ${ssa.current[project.primaryInterventionId]})`);
    }
  }

  return CATEGORY_META.map((m) => ({ ...m, items: buckets[m.key] }));
}

/** Total open project-planning items (for dashboard badges). */
export function projectPlanningGapCount(categories: ProjectGapCategory[]): number {
  return categories.reduce((a, c) => a + c.items.length, 0);
}
