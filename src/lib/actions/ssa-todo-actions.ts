"use server";

// Complete an SSA verification todo. Mirrors the canonical Bucket-C shape:
// resolve actor, gate by role, validate, persist the EXACT entered ID, emit
// one audit row + notify, revalidate, return a discriminated union.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { ssaVerificationTodos, nextOctoberFinancialYear } from "@/lib/ssa-mock";
import {
  ssaTodoCompletionFor,
  recordSsaTodoCompletion,
  type SsaTodoFlag,
} from "@/lib/ssa/verification-todos";
import { emitAudit, emitNotification } from "./audit";

export type CompleteSsaTodoResult =
  | { ok: true; todoId: string; ssaVerificationId: string; flag: SsaTodoFlag; newStatus: "Verified" | "Closed" }
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_INPUT" }
  | { ok: false; reason: "DUPLICATE" };

// SSA verification is performed by field staff (CCEO) and signed off by M&E /
// leadership. Defence-in-depth even though the page is gated.
const ROLES = new Set(["ImpactAssessment", "CCEO", "CountryProgramLead", "CountryDirector", "Admin"]);

export async function completeSsaVerificationTodo(
  todoId: string,
  ssaVerificationId: string,
): Promise<CompleteSsaTodoResult> {
  const user = await getCurrentUser();
  if (!ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const todo = ssaVerificationTodos.find((t) => t.todoId === todoId);
  if (!todo) return { ok: false, reason: "NOT_FOUND" };

  // Store the exact entered id; require something meaningful.
  const enteredId = ssaVerificationId?.trim() ?? "";
  if (enteredId.length < 3) return { ok: false, reason: "INVALID_INPUT" };

  if (ssaTodoCompletionFor(todoId)) return { ok: false, reason: "DUPLICATE" };

  // These todos are auto-created only for Client schools at SSA 7.5+ across all
  // 8 interventions, so a confirmed verification flags them Potential Core and
  // recommends October onboarding (mirrors confirmSsaVerificationId's 7.5 path).
  const flag: SsaTodoFlag = "Potential Core School";
  const newStatus = "Verified" as const;
  const octoberFy = nextOctoberFinancialYear();

  recordSsaTodoCompletion({
    todoId,
    ssaVerificationId: enteredId,
    flag,
    newStatus,
    octoberFy,
    completedAt: new Date().toISOString(),
    completedById: user.staffId,
    completedByName: user.name,
  });

  emitAudit({
    action: "ssaVerificationTodo.completed",
    subjectKind: "SsaVerificationTodo",
    subjectId: todoId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { ssaVerificationId: enteredId, schoolId: todo.schoolId, flag, octoberFy },
  });

  emitNotification({
    userId: todo.assignedStaffId,
    template: "ssaVerificationTodo.completed",
    channel: "Inbox",
    title: `SSA verified for ${todo.schoolName}`,
    body: `Verification ID ${enteredId} recorded — flagged ${flag}, recommended for October onboarding (${octoberFy}).`,
    href: "/ssa/core-candidates",
  });

  try {
    revalidatePath("/ssa/core-candidates");
    revalidatePath("/ssa");
  } catch {
    /* outside request scope — fine */
  }

  return { ok: true, todoId, ssaVerificationId: enteredId, flag, newStatus };
}
