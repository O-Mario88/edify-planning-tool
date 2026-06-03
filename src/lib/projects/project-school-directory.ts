// Project-grouped school directory (the "Special Project Schools" surface).
//
// Unlike the general School Directory (every uploaded school), this builds one
// card PER PROJECT, each holding ONLY the schools actively assigned to that
// project — a mini school-portfolio per project. Source of truth stays the
// School Directory: a row appears only when it both (a) has an active
// SchoolProjectMembership and (b) exists in the directory within the user's
// scope. Never the full directory; never unassigned schools.

import {
  getVisibleProjects,
  schoolProjectMemberships,
  PROJECT_CATEGORY_LABEL,
  type SpecialProject,
  type ProjectCategory,
} from "@/lib/special-projects-mock";
import type { CurrentUser } from "@/lib/schools-mock";
import { intakeSchools, type IntakeSchool } from "@/lib/intake/intake-mock";
import { ssaForSchool } from "./project-school-ssa";
import { activitiesForProjectSchool } from "./project-activities";

export type TriStatus = "Completed" | "Scheduled" | "Needed";
export type ProjectImpactStatus = "Improved" | "Declined" | "No Change" | "No Comparison";

export type ProjectSchoolRowVM = {
  schoolId: string;
  schoolName: string;
  region: string;
  district: string;
  subCounty?: string;
  cluster?: string;
  accountOwner?: string;
  schoolType: string;
  ssaStatus: string;
  // Project-specific (mapped intervention)
  baselineScore?: number;
  latestScore?: number;
  change?: number;
  impactStatus: ProjectImpactStatus;
  // Activity-derived sub-statuses
  trainingStatus: TriStatus;
  followUpStatus: TriStatus;
  evidenceStatus: "Verified" | "Pending" | "None";
  salesforceStatus: "Entered" | "Missing" | "N/A";
  iaStatus: "Verified" | "Pending" | "None";
  partnerSupport?: string;
  // Headline project status + the single next action
  projectStatus: string;
  nextAction: string;
};

export type ProjectCardMetrics = {
  assigned: number;
  trained: number;
  followedUp: number;
  assessed: number;
  evidencePending: number;
  iaVerified: number;
  improved: number;
};

export type ProjectCardImpact = {
  intervention: string;
  baselineAvg: number;
  latestAvg: number;
  change: number;
  schoolsImproved: number;
  schoolsWithComparison: number;
};

export type ProjectCardVM = {
  project: SpecialProject;
  categoryLabel: string;
  metrics: ProjectCardMetrics;
  impact: ProjectCardImpact;
  schools: ProjectSchoolRowVM[];
};

export type ProjectSchoolDirectory = {
  cards: ProjectCardVM[];
  summary: {
    activeProjects: number;
    projectSchools: number;
    schoolsTrained: number;
    followUpsCompleted: number;
    schoolsImproved: number;
    evidencePending: number;
  };
};

// ── Row builders ──

function activeSchoolIdsForProject(projectId: string): string[] {
  return schoolProjectMemberships
    .filter((m) => m.projectId === projectId && m.status === "Active")
    .map((m) => m.schoolId);
}

function buildRow(project: SpecialProject, school: IntakeSchool): ProjectSchoolRowVM {
  const intervention = project.primaryInterventionId;
  const ssa = ssaForSchool(school.schoolId);
  const baselineScore = ssa?.baseline[intervention];
  const latestScore = ssa?.current[intervention];
  const change =
    baselineScore !== undefined && latestScore !== undefined
      ? Math.round((latestScore - baselineScore) * 10) / 10
      : undefined;
  const impactStatus: ProjectImpactStatus =
    change === undefined ? "No Comparison" : change > 0 ? "Improved" : change < 0 ? "Declined" : "No Change";

  const acts = activitiesForProjectSchool(project.projectId, school.schoolId);
  const trainings = acts.filter((a) => a.activityType === "Project Training");
  const followUps = acts.filter((a) => a.activityType === "Project Follow-Up Visit");
  const triStatus = (rows: typeof acts): TriStatus =>
    rows.some((a) => a.status === "Completed") ? "Completed"
    : rows.some((a) => a.status === "Planned" || a.status === "In Progress") ? "Scheduled"
    : "Needed";
  const trainingStatus = triStatus(trainings);
  const followUpStatus = triStatus(followUps);

  const completed = acts.filter((a) => a.status === "Completed");
  const evidenceStatus: ProjectSchoolRowVM["evidenceStatus"] =
    completed.length === 0 ? "None"
    : completed.every((a) => a.evidenceStatus === "Verified") ? "Verified"
    : "Pending";
  const salesforceStatus: ProjectSchoolRowVM["salesforceStatus"] =
    completed.length === 0 ? "N/A"
    : completed.every((a) => Boolean(a.salesforceActivityId)) ? "Entered"
    : "Missing";
  const iaStatus: ProjectSchoolRowVM["iaStatus"] =
    completed.some((a) => a.iaVerificationStatus === "Confirmed") ? "Verified"
    : completed.some((a) => a.iaVerificationStatus === "Submitted") ? "Pending"
    : "None";
  const partnerSupport = acts.find((a) => a.deliveryType === "partner")?.partnerName;

  // Headline status + next action (project-specific, never replaces school status).
  let projectStatus = "Assigned to Project";
  let nextAction = "Schedule training";
  if (trainingStatus === "Needed") { projectStatus = "Training Needed"; nextAction = "Schedule training"; }
  else if (trainingStatus === "Scheduled") { projectStatus = "Training Scheduled"; nextAction = "Deliver training"; }
  else { // training completed
    if (evidenceStatus === "Pending") { projectStatus = "Evidence Pending"; nextAction = "Upload / accept evidence"; }
    else if (salesforceStatus === "Missing") { projectStatus = "Salesforce ID Missing"; nextAction = "Enter Salesforce ID"; }
    else if (iaStatus === "Pending") { projectStatus = "Awaiting IA Verification"; nextAction = "Await IA"; }
    else if (followUpStatus !== "Completed") { projectStatus = "Follow-Up Needed"; nextAction = "Schedule follow-up"; }
    else if (impactStatus === "Improved") { projectStatus = "Improved"; nextAction = "Monitor"; }
    else if (impactStatus === "Declined") { projectStatus = "Declined"; nextAction = "Re-plan support"; }
    else if (impactStatus === "No Comparison") { projectStatus = "Awaiting Next SSA"; nextAction = "Schedule SSA"; }
    else { projectStatus = "No Improvement Yet"; nextAction = "Re-plan support"; }
  }

  return {
    schoolId: school.schoolId,
    schoolName: school.schoolName,
    region: school.region,
    district: school.district,
    subCounty: school.subCounty,
    cluster: school.cluster,
    accountOwner: school.assignedCceo,
    schoolType: school.schoolType,
    ssaStatus: school.ssaStatus,
    baselineScore, latestScore, change, impactStatus,
    trainingStatus, followUpStatus, evidenceStatus, salesforceStatus, iaStatus,
    partnerSupport,
    projectStatus, nextAction,
  };
}

function metricsFor(rows: ProjectSchoolRowVM[]): ProjectCardMetrics {
  return {
    assigned: rows.length,
    trained: rows.filter((r) => r.trainingStatus === "Completed").length,
    followedUp: rows.filter((r) => r.followUpStatus === "Completed").length,
    assessed: rows.filter((r) => r.iaStatus === "Verified").length,
    evidencePending: rows.filter((r) => r.evidenceStatus === "Pending").length,
    iaVerified: rows.filter((r) => r.iaStatus === "Verified").length,
    improved: rows.filter((r) => r.impactStatus === "Improved").length,
  };
}

function impactFor(intervention: string, rows: ProjectSchoolRowVM[]): ProjectCardImpact {
  const withBoth = rows.filter((r) => r.baselineScore !== undefined && r.latestScore !== undefined);
  const n = withBoth.length || 1;
  const baselineAvg = withBoth.reduce((a, r) => a + (r.baselineScore ?? 0), 0) / n;
  const latestAvg = withBoth.reduce((a, r) => a + (r.latestScore ?? 0), 0) / n;
  return {
    intervention,
    baselineAvg: Math.round(baselineAvg * 10) / 10,
    latestAvg: Math.round(latestAvg * 10) / 10,
    change: Math.round((latestAvg - baselineAvg) * 10) / 10,
    schoolsImproved: rows.filter((r) => r.impactStatus === "Improved").length,
    schoolsWithComparison: withBoth.length,
  };
}

/**
 * Build the project-grouped directory for a user.
 *
 * @param currentUser  drives project visibility (getVisibleProjects).
 * @param scopedSchoolIds  when a Set, only these school ids are shown inside
 *   cards (CCEO portfolio / PL team scope). When "all", every assigned school
 *   in a visible project shows (CD / Admin / Coordinator / IA).
 */
export function buildProjectSchoolDirectory(
  currentUser: CurrentUser,
  scopedSchoolIds: Set<string> | "all",
): ProjectSchoolDirectory {
  const projects = getVisibleProjects(currentUser);
  const cards: ProjectCardVM[] = [];

  for (const project of projects) {
    const ids = activeSchoolIdsForProject(project.projectId).filter(
      (id) => scopedSchoolIds === "all" || scopedSchoolIds.has(id),
    );
    if (ids.length === 0) continue;
    const rows = ids
      .map((id) => intakeSchools.find((s) => s.schoolId === id))
      .filter((s): s is IntakeSchool => Boolean(s))
      .map((s) => buildRow(project, s))
      .sort((a, b) => a.schoolName.localeCompare(b.schoolName));
    if (rows.length === 0) continue;

    cards.push({
      project,
      categoryLabel: PROJECT_CATEGORY_LABEL[project.projectCategory as ProjectCategory] ?? "Project",
      metrics: metricsFor(rows),
      impact: impactFor(project.primaryInterventionId, rows),
      schools: rows,
    });
  }

  // Most-populated cards first.
  cards.sort((a, b) => b.metrics.assigned - a.metrics.assigned);

  const summary = {
    activeProjects: cards.length,
    projectSchools: cards.reduce((a, c) => a + c.metrics.assigned, 0),
    schoolsTrained: cards.reduce((a, c) => a + c.metrics.trained, 0),
    followUpsCompleted: cards.reduce((a, c) => a + c.metrics.followedUp, 0),
    schoolsImproved: cards.reduce((a, c) => a + c.metrics.improved, 0),
    evidencePending: cards.reduce((a, c) => a + c.metrics.evidencePending, 0),
  };

  return { cards, summary };
}
