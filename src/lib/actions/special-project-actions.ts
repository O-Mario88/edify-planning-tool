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
  canManageProjectCategory,
  type CreateProjectInput,
} from "@/lib/special-projects-mock";
import {
  createProjectActivity,
  type CreateProjectActivityInput,
} from "@/lib/projects/project-activities";
import { assignProjectSchool, removeProjectSchool } from "@/lib/api/surfaces";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { schoolWorkflowState } from "@/lib/school-directory/school-state";

// Spine gate — a school must clear the planning prerequisites before
// project tagging. Returns ok:false with a human reason when it
// hasn't (unclustered, no SSA, owner unresolved, etc.).
function projectAssignmentGateFor(schoolId: string): { ok: true } | { ok: false; reason: string } {
  const s = intakeSchools.find((x) => x.schoolId === schoolId);
  if (!s) return { ok: true }; // backend-only schools — backend enforces its own gate
  const state = schoolWorkflowState(s);
  if (state.stage === "planning_ready") return { ok: true };
  const reasonMap: Record<string, string> = {
    needs_owner:   "School owner is unresolved. Map it in the IA queue before tagging into a project.",
    duplicate:     "School is flagged as a possible duplicate. Resolve it in the IA queue first.",
    unclustered:   "Assign the school to a cluster before tagging it into a project.",
    ssa_required:  "Upload a first SSA before tagging the school into a project.",
  };
  return {
    ok: false,
    reason: reasonMap[state.stage] ?? `School is at ${state.stageLabel}; complete planning prerequisites first.`,
  };
}

const PROJECT_ROLES = new Set<string>([
  "CCEO",
  "CountryProgramLead",
  "CountryDirector",
  "ImpactAssessment",
  "ProjectCoordinator",
  "Admin",
]);

// Management is gated by PROJECT CATEGORY (spec): CCEO/PL run intervention-
// specific projects; pilot & selective projects need coordination scope.
// Returns FORBIDDEN-style false when the role may not manage the project's
// category, or when the project can't be found.
function canManageProjectById(role: string, projectId: string): boolean {
  const project = projectById(projectId);
  if (!project) return false;
  return canManageProjectCategory(role, project.projectCategory);
}

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
  if (!canManageProjectById(user.role, projectId)) return { ok: false, reason: "FORBIDDEN" };

  // Spine gate: a special project assignment is real planning work, so
  // the school must be plannable (clustered + SSA done). Otherwise the
  // project tag attaches to a locked school and downstream analytics
  // count work that can't happen.
  const gate = projectAssignmentGateFor(schoolId);
  if (!gate.ok) {
    return { ok: false, reason: "FAILED", message: gate.reason };
  }

  // Backend is the source of truth when enabled: it validates the school against
  // the real School Directory, enforces the permission, persists the assignment,
  // and writes an audit log. We then mirror into the mock so the FE's project
  // tag/directory pages reflect it immediately. Backend OFF → mock-only.
  const be = await assignProjectSchool(user, projectId, schoolId);
  if (be.live === false && be.error) return { ok: false, reason: "FAILED", message: be.error };

  const res = assignSchoolToProject({
    schoolId,
    projectId,
    assignedByName: user.name,
    assignedByStaffId: user.staffId,
  });
  // Only fail on the mock when the backend didn't already persist it.
  if (!be.live && !res.ok) return { ok: false, reason: "FAILED", message: res.reason };

  const project = specialProjects.find((p) => p.projectId === projectId);
  emitAudit({
    action: "specialProject.schoolAssigned",
    subjectKind: "School",
    subjectId: schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { projectId, projectName: project?.projectName, persisted: be.live ? "backend" : "mock" },
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
  if (!canManageProjectById(user.role, projectId)) return { ok: false, reason: "FORBIDDEN" };
  if (!schoolIds.length) return { ok: false, reason: "FAILED", message: "Select at least one school." };

  let assigned = 0;
  let skipped = 0;
  for (const schoolId of schoolIds) {
    // Spine gate per-school — same as the single-school action above.
    if (!projectAssignmentGateFor(schoolId).ok) { skipped += 1; continue; }
    // Backend first (source of truth + Directory validation), then mirror to mock.
    const be = await assignProjectSchool(user, projectId, schoolId);
    if (be.live === false && be.error) { skipped += 1; continue; }
    const res = assignSchoolToProject({
      schoolId,
      projectId,
      assignedByName: user.name,
      assignedByStaffId: user.staffId,
    });
    if (be.live || res.ok) assigned += 1;
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
  if (!canManageProjectById(user.role, projectId)) return { ok: false, reason: "FORBIDDEN" };
  // Backend first (source of truth + audit), then mirror to the mock.
  const be = await removeProjectSchool(user, projectId, schoolId);
  if (be.live === false && be.error) return { ok: false, reason: "FAILED", message: be.error };
  const ok = removeSchoolFromProject(schoolId, projectId);
  if (!be.live && !ok) return { ok: false, reason: "FAILED", message: "Membership not found." };
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
  // Category decides who may create: intervention-specific → CCEO/PL/CD/coord;
  // pilot & selective → coordinator/CD/PL (CCEO excluded).
  if (!input.projectCategory) return { ok: false, reason: "FAILED", message: "Choose a project category." };
  if (!canManageProjectCategory(user.role, input.projectCategory)) return { ok: false, reason: "FORBIDDEN" };

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
  if (!canManageProjectById(user.role, input.projectId)) return { ok: false, reason: "FORBIDDEN" };

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
  if (!canManageProjectById(user.role, projectId)) return { ok: false, reason: "FORBIDDEN" };
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
