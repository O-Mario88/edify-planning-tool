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
  specialProjects,
} from "@/lib/special-projects-mock";

const PROJECT_ROLES = new Set<string>([
  "CCEO",
  "CountryProgramLead",
  "CountryDirector",
  "ImpactAssessment",
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
