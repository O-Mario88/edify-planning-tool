"use server";

// Special-project assignment server actions — the write path for tagging a
// school into a special project from the School Directory / Portfolio (the same
// surface as cluster assignment). Membership delegates participation only; it
// never changes ownership — the school stays in its account owner's portfolio.
//
// Who can assign: Staff/CCEO, Program Lead, Country Director, IA, Admin.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit } from "./audit";
import {
  assignSchoolToProject,
  removeSchoolFromProject,
  createProject,
  projectById,
  specialProjects,
  CCEO_ALLOWED_PROJECT_TYPES,
  type CreateProjectInput,
} from "@/lib/special-projects-mock";
import {
  createProjectActivity,
  type CreateProjectActivityInput,
} from "@/lib/projects/project-activities";

const PROJECT_ROLES = new Set<string>([
  "CCEO",
  "CountryProgramLead",
  "CountryDirector",
  "ImpactAssessment",
  "ProjectCoordinator",
  "Admin",
]);

// Who may create / manage projects. CCEO is allowed only for local targeted
// interventions (spec §9) — enforced per-type in createProjectAction.
const PROJECT_CREATE_ROLES = new Set<string>([
  "ProjectCoordinator",
  "CountryDirector",
  "CountryProgramLead",
  "Admin",
]);

export type ProjectActionResult<T = Record<string, unknown>> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "FAILED"; message: string };

function revalidateProjectSurfaces() {
  try {
    revalidatePath("/schools");
    revalidatePath("/portfolio");
    revalidatePath("/special-projects");
    revalidatePath("/analytics");
  } catch {
    /* outside request */
  }
}

// ─── Assign one school to a special project ─────────────────────────

export async function assignSchoolToProjectAction(
  schoolId: string,
  projectId: string,
): Promise<ProjectActionResult<{ projectName: string }>> {
  const user = await getCurrentUser();
  if (!PROJECT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const res = assignSchoolToProject({
    schoolId,
    projectId,
    assignedByName: user.name,
    assignedByStaffId: user.staffId,
  });
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };

  const project = specialProjects.find((p) => p.projectId === projectId);
  emitAudit({
    action: "specialProject.schoolAssigned",
    subjectKind: "School",
    subjectId: schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { projectId, projectName: project?.projectName },
  });
  revalidateProjectSurfaces();
  return { ok: true, projectName: project?.projectShortName ?? projectId };
}

// ─── Bulk assign many schools to one special project ────────────────

export async function assignSchoolsToProjectAction(
  schoolIds: string[],
  projectId: string,
): Promise<ProjectActionResult<{ assigned: number; skipped: number }>> {
  const user = await getCurrentUser();
  if (!PROJECT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!schoolIds.length) return { ok: false, reason: "FAILED", message: "Select at least one school." };

  let assigned = 0;
  let skipped = 0;
  for (const schoolId of schoolIds) {
    const res = assignSchoolToProject({
      schoolId,
      projectId,
      assignedByName: user.name,
      assignedByStaffId: user.staffId,
    });
    if (res.ok) assigned += 1;
    else skipped += 1;
  }

  if (assigned > 0) {
    const project = specialProjects.find((p) => p.projectId === projectId);
    emitAudit({
      action: "specialProject.schoolsAssigned",
      subjectKind: "Project",
      subjectId: projectId,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: { projectId, projectName: project?.projectName, assigned, skipped },
    });
    revalidateProjectSurfaces();
  }
  return { ok: true, assigned, skipped };
}

// ─── Remove a school from a special project ─────────────────────────

export async function removeSchoolFromProjectAction(
  schoolId: string,
  projectId: string,
): Promise<ProjectActionResult> {
  const user = await getCurrentUser();
  if (!PROJECT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const ok = removeSchoolFromProject(schoolId, projectId);
  if (!ok) return { ok: false, reason: "FAILED", message: "Membership not found." };
  emitAudit({
    action: "specialProject.schoolRemoved",
    subjectKind: "School",
    subjectId: schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { projectId },
  });
  revalidateProjectSurfaces();
  return { ok: true };
}

// ─── Create a special project (spec §3/§9) ──────────────────────────

export async function createProjectAction(
  input: CreateProjectInput,
): Promise<ProjectActionResult<{ projectId: string; projectName: string }>> {
  const user = await getCurrentUser();
  const canCreate =
    PROJECT_CREATE_ROLES.has(user.role) ||
    // CCEO may create local targeted interventions only.
    (user.role === "CCEO" && CCEO_ALLOWED_PROJECT_TYPES.has(input.projectType));
  if (!canCreate) return { ok: false, reason: "FORBIDDEN" };

  if (!input.projectName?.trim()) return { ok: false, reason: "FAILED", message: "Project name is required." };
  if (!input.primaryInterventionId) return { ok: false, reason: "FAILED", message: "Pick a primary SSA intervention." };
  if (!input.startDate || !input.endDate) return { ok: false, reason: "FAILED", message: "Set a start and end date." };

  const project = createProject(input, { staffId: user.staffId, role: user.role, name: user.name });
  emitAudit({
    action: "specialProject.created",
    subjectKind: "Project",
    subjectId: project.projectId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      projectName: project.projectName,
      projectType: project.projectType,
      primaryInterventionId: project.primaryInterventionId,
    },
  });
  revalidateProjectSurfaces();
  return { ok: true, projectId: project.projectId, projectName: project.projectName };
}

// ─── Schedule a project activity (training / follow-up / etc.) ──────

export async function scheduleProjectActivityAction(
  input: CreateProjectActivityInput,
): Promise<ProjectActionResult<{ activityId: string }>> {
  const user = await getCurrentUser();
  if (!PROJECT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const res = createProjectActivity(input);
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };

  emitAudit({
    action: "specialProject.activityScheduled",
    subjectKind: "Project",
    subjectId: input.projectId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { activityType: input.activityType, schoolId: input.schoolId },
  });
  revalidateProjectSurfaces();
  return { ok: true, activityId: res.activity.id };
}

// ─── Assign a project to a partner (execution only; ownership unchanged) ─

export async function assignProjectToPartnerAction(
  projectId: string,
  partnerName: string,
  scope?: string,
): Promise<ProjectActionResult<{ partnerName: string }>> {
  const user = await getCurrentUser();
  if (!PROJECT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!partnerName.trim()) return { ok: false, reason: "FAILED", message: "Enter a partner name." };

  const project = projectById(projectId);
  if (!project) return { ok: false, reason: "FAILED", message: "Project not found." };
  project.assignedPartnerName = partnerName.trim();

  emitAudit({
    action: "specialProject.partnerAssigned",
    subjectKind: "Project",
    subjectId: projectId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { partnerName: partnerName.trim(), scope },
  });
  revalidateProjectSurfaces();
  return { ok: true, partnerName: partnerName.trim() };
}
