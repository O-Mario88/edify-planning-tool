"use server";

// My Plan loop — the plan-as-list actions. Scheduling from a school/cluster
// CREATES a Planned activity here; the My Plan list then acts on each row:
// Reschedule (with reason + slip limit), Reassign (staff ↔ partner),
// Cancel/Defer, Complete (the existing markActivityCompleted path).
//
// Demo store (in-memory, globalThis-backed) — production swaps the array ops for
// Prisma. Every mutation revalidates the surfaces that render the plan.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import {
  activities, findActivity, updateActivity, newId,
  type ActivityKind, type PlannedActivityRecord,
} from "@/lib/actions/store";
import { emitAudit, emitNotification } from "@/lib/actions/audit";
import { canReschedule } from "@/lib/planning/planning-capacity";
import { computeStaffCapacity, staffAlreadySupportsSchool, type StaffCapacity } from "@/lib/planning/assignment-policy";
import { cceosSupervisedBy, supervisorOf } from "@/lib/org/supervision";
import { DEMO_USERS } from "@/lib/auth";
import { isBackendEnabled } from "@/lib/api/backend";
import { backendActivityAction, backendCreateActivity, type ActivityLifecycleAction } from "@/lib/api/surfaces";

// Backend-first: when EDIFY_USE_BACKEND is on, run the lifecycle action against
// the backend (the enforced, authoritative source). Returns true if the backend
// handled it; false → caller falls back to the in-memory store (e.g. activities
// that only exist in the mock store, keyed by non-backend ids).
async function tryBackend(id: string, action: ActivityLifecycleAction, body: Record<string, unknown>): Promise<boolean> {
  if (!isBackendEnabled()) return false;
  const user = await getCurrentUser();
  const r = await backendActivityAction(user, id, action, body);
  return r.live;
}

// CD/IA recipients for capacity escalations (spec §21).
function cdIaStaffIds(): string[] {
  return Object.values(DEMO_USERS).filter((u) => u.role === "CountryDirector" || u.role === "ImpactAssessment").map((u) => u.staffId);
}

// Fire near/at-limit notifications after a staff self-assign crosses a threshold.
function notifyCapacity(staffId: string, staffName: string, cap: StaffCapacity) {
  if (cap.atLimit) {
    const sup = supervisorOf(staffId)?.staffId;
    const recipients = [staffId, ...(sup ? [sup] : []), ...cdIaStaffIds()];
    for (const r of new Set(recipients)) {
      emitNotification({ userId: r, template: "capacity.atLimit", channel: "Inbox", title: "Direct support limit reached", body: r === staffId ? `You've reached your direct support limit (${cap.max} schools). New school support should be assigned to a partner.` : `${staffName} has reached their direct support limit (${cap.max}). New school support should go to a partner.`, href: "/capacity" });
    }
  } else if (cap.nearLimit) {
    const sup = supervisorOf(staffId)?.staffId;
    for (const r of new Set([staffId, ...(sup ? [sup] : [])])) {
      emitNotification({ userId: r, template: "capacity.nearLimit", channel: "Inbox", title: "Direct support capacity near limit", body: `${r === staffId ? "You have" : staffName + " has"} used ${cap.used}/${cap.max} of direct support capacity (≥90%).`, href: "/capacity" });
    }
  }
}

export type MyPlanResult =
  | { ok: true; id: string }
  | { ok: false; reason: "NOT_FOUND" | "SLIP_LIMIT" | "FORBIDDEN" | "INVALID_INPUT" | "CAPACITY_FULL"; message?: string };

// Can this user act on this activity's lifecycle? Owner (assignee), the
// assignee's supervisor (PL acting for a supervised CCEO, CD for a PL),
// or Admin. WITHOUT this guard every My Plan row action was a public
// mutation endpoint — any authenticated session could reschedule,
// reassign, cancel, defer, or COMPLETE any activity in the store, since
// the getCurrentUser() call only stamped the audit row.
function canActOnActivity(
  user: { staffId: string; role: string },
  activity: PlannedActivityRecord,
): boolean {
  if (user.role === "Admin") return true;
  if (activity.assigneeId && activity.assigneeId === user.staffId) return true;
  if (activity.assigneeId) {
    const sup = supervisorOf(activity.assigneeId);
    if (sup?.staffId === user.staffId) return true;
  }
  return false;
}

const TITLE: Record<string, string> = {
  SCHOOL_VISIT: "School visit", IN_SCHOOL_COACHING: "In-school coaching",
  SSA_FOLLOW_UP: "SSA follow-up visit", COURTESY_VISIT: "Courtesy visit",
  CLUSTER_TRAINING: "Cluster training", TRAINING_FOLLOW_UP: "Training follow-up",
  HANDOVER_MEETING: "Cluster meeting", LESSON_OBSERVATION: "Lesson observation",
  PARTNER_FOLLOW_UP: "Partner follow-up", DATA_COLLECTION: "Data collection",
};

function weekOfMonth(iso?: string): number {
  if (!iso) return 1;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 1;
  return Math.min(5, Math.max(1, Math.ceil(d.getUTCDate() / 7)));
}

// FE ActivityKind → backend ActivityType.
const KIND_TO_BE: Record<string, string> = {
  SCHOOL_VISIT: "school_visit", IN_SCHOOL_COACHING: "coaching_visit", SSA_FOLLOW_UP: "follow_up_visit",
  COURTESY_VISIT: "school_visit", LESSON_OBSERVATION: "school_visit", PARTNER_FOLLOW_UP: "follow_up_visit",
  TRAINING_FOLLOW_UP: "school_improvement_training", CLUSTER_TRAINING: "cluster_training",
  HANDOVER_MEETING: "cluster_meeting", DATA_COLLECTION: "school_visit",
};

// FY ("2026") + quarter ("Q1".."Q4", FY starts Oct) from a date.
function fyQuarter(iso?: string): { fy: string; quarter: string } {
  const d = iso ? new Date(iso) : new Date();
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth(); // 0-11
  const fy = String(m >= 9 ? y + 1 : y);
  const quarter = m >= 9 ? "Q1" : m <= 2 ? "Q2" : m <= 5 ? "Q3" : "Q4";
  return { fy, quarter };
}

function revalidate(schoolId?: string) {
  try {
    revalidatePath("/plans");
    revalidatePath("/planning");
    revalidatePath("/my-plan");
    revalidatePath("/today");
    revalidatePath("/calendar");
    revalidatePath("/team-plan");
    revalidatePath("/dashboards/cceo");
    revalidatePath("/dashboards/cpl");
    if (schoolId) revalidatePath(`/schools/${schoolId}`);
  } catch { /* outside a request scope (e.g. tests) */ }
}

// ── Create from school / cluster ────────────────────────────────────
export async function scheduleSchoolActivity(input: {
  schoolId: string;
  schoolName?: string;
  kind: ActivityKind;
  dateIso?: string;
  deliveryType?: "staff" | "partner";
  partnerName?: string;
  /** Real backend partner id — set when assigning to a specific partner. */
  partnerId?: string;
  /** Explicit backend ActivityType (e.g. "core_visit", "school_improvement_training").
   *  Overrides the KIND_TO_BE mapping so core + training activities persist with the
   *  correct type. The mock-store fallback still uses `kind` for its title. */
  backendActivityType?: string;
  /** Visit scheduling by month/week (no exact date). */
  plannedMonth?: number;
  plannedWeek?: number;
}): Promise<MyPlanResult> {
  const user = await getCurrentUser();
  if (!input.schoolId || !input.kind) return { ok: false, reason: "INVALID_INPUT" };

  const toPartner = input.deliveryType === "partner";

  // ── Backend-first create (write-path migration) ──────────────────
  // When the backend is on AND the school exists there (backend schoolId), the
  // create is persisted + enforced by the API. A 403 is the real capacity block
  // (surface it); a 404 means the school only exists in the mock store (fall back).
  if (isBackendEnabled()) {
    const { fy, quarter } = fyQuarter(input.dateIso);
    const r = await backendCreateActivity(user, {
      activityType: input.backendActivityType ?? KIND_TO_BE[input.kind] ?? "school_visit",
      schoolId: input.schoolId, fy, quarter,
      deliveryType: toPartner ? "partner" : "staff",
      ...(toPartner && input.partnerId ? { assignedPartnerId: input.partnerId } : {}),
      ...(input.plannedMonth ? { plannedMonth: input.plannedMonth } : {}),
      ...(input.plannedWeek ? { plannedWeek: input.plannedWeek } : {}),
      ...(input.dateIso ? { scheduledDate: input.dateIso } : {}),
    });
    if (r.live) { revalidate(input.schoolId); return { ok: true, id: r.data.id }; }
    if (r.error && r.error.includes("403")) {
      return { ok: false, reason: "CAPACITY_FULL", message: "Direct support limit reached. Assign this to a partner." };
    }
    // 404 / other → fall through to the in-memory store (mock-id school).
  }

  // ── Backend assignment enforcement (spec §6/§9) — never frontend-only. ──
  if (!toPartner) {
    // Self / staff-delivered support: role + direct support capacity gate.
    if (user.role !== "CCEO" && user.role !== "CountryProgramLead") {
      return { ok: false, reason: "FORBIDDEN", message: "Your role does not deliver direct school support." };
    }
    const cap = computeStaffCapacity(user.staffId);
    const already = staffAlreadySupportsSchool(user.staffId, input.schoolId);
    if (!already && cap.remaining <= 0) {
      emitAudit({ action: "myplan.assignment.blocked", subjectKind: "School", subjectId: input.schoolId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { reason: "CAPACITY_FULL", max: cap.max, used: cap.used } });
      return { ok: false, reason: "CAPACITY_FULL", message: `Direct support limit reached (${cap.max} schools). Assign this to a partner.` };
    }
  }

  const now = new Date().toISOString();
  const act: PlannedActivityRecord = {
    id: newId("act"),
    planId: `MYPLAN-${user.staffId}`,
    schoolId: input.schoolId,
    schoolName: input.schoolName,
    kind: input.kind,
    title: `${TITLE[input.kind] ?? "Activity"}${input.schoolName ? ` — ${input.schoolName}` : ""}`,
    weekOfMonth: weekOfMonth(input.dateIso),
    scheduledDate: input.dateIso,
    assigneeId: user.staffId,
    estCostCents: 0,
    status: "Planned",
    deliveryType: input.deliveryType ?? "staff",
    partnerName: input.deliveryType === "partner" ? input.partnerName : undefined,
    rescheduleCount: 0,
    createdAt: now,
    updatedAt: now,
  };
  activities().push(act);
  emitAudit({ action: "myplan.activity.scheduled", subjectKind: "Activity", subjectId: act.id, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { schoolId: input.schoolId, kind: input.kind } });
  // Near/at-limit escalation after a staff self-assign (spec §21).
  if (!toPartner) notifyCapacity(user.staffId, user.name, computeStaffCapacity(user.staffId));
  // Partner-delivered: push to the partner so they see the new
  // assignment immediately instead of discovering it on their next
  // dashboard visit. Looked up by name (best-effort) — partners that
  // can't be resolved skip the notify, audit still fires.
  if (toPartner && input.partnerName) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { partners } = require("@/lib/partner/partner-mock") as
      typeof import("@/lib/partner/partner-mock");
    const partner = partners.find(
      (p: { name: string; shortName?: string }) =>
        p.name === input.partnerName || p.shortName === input.partnerName,
    );
    if (partner) {
      emitNotification({
        userId: partner.id,
        template: "partnerActivity.assigned",
        channel: "Inbox",
        title: `New activity assigned: ${act.title}`,
        body: `${user.name} routed ${TITLE[input.kind] ?? "an activity"} at ${input.schoolName ?? input.schoolId} to you.`,
        href: "/partner/today",
      });
    }
  }
  revalidate(input.schoolId);
  return { ok: true, id: act.id };
}

// ── PL → supervised CCEO (the other half of the assignment rules) ───
export async function assignActivityToStaff(input: {
  schoolId: string;
  schoolName?: string;
  kind: ActivityKind;
  dateIso?: string;
  targetStaffId: string;
}): Promise<MyPlanResult> {
  const user = await getCurrentUser();
  // Only a PL can assign to a CCEO, and only to a CCEO they supervise (spec §17).
  if (user.role !== "CountryProgramLead") {
    return { ok: false, reason: "FORBIDDEN", message: "Only a Program Lead can assign to a supervised CCEO." };
  }
  const target = cceosSupervisedBy(user.staffId).find((c) => c.staffId === input.targetStaffId);
  if (!target) {
    return { ok: false, reason: "FORBIDDEN", message: "That CCEO is not on your supervised team." };
  }
  // The TARGET CCEO's direct-support capacity gates the assignment.
  const cap = computeStaffCapacity(target.staffId);
  const already = staffAlreadySupportsSchool(target.staffId, input.schoolId);
  if (!already && cap.remaining <= 0) {
    emitAudit({ action: "myplan.assignment.blocked", subjectKind: "School", subjectId: input.schoolId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { reason: "TARGET_CAPACITY_FULL", targetStaffId: target.staffId } });
    return { ok: false, reason: "CAPACITY_FULL", message: `${target.name} is at their support limit (${cap.max} schools). Assign to a partner or another CCEO.` };
  }

  const now = new Date().toISOString();
  const act: PlannedActivityRecord = {
    id: newId("act"),
    planId: `MYPLAN-${target.staffId}`,
    schoolId: input.schoolId,
    schoolName: input.schoolName,
    kind: input.kind,
    title: `${TITLE[input.kind] ?? "Activity"}${input.schoolName ? ` — ${input.schoolName}` : ""}`,
    weekOfMonth: weekOfMonth(input.dateIso),
    scheduledDate: input.dateIso,
    assigneeId: target.staffId, // owned by the CCEO
    estCostCents: 0,
    status: "Planned",
    deliveryType: "staff",
    rescheduleCount: 0,
    createdAt: now,
    updatedAt: now,
  };
  activities().push(act);
  emitAudit({ action: "myplan.activity.assignedToStaff", subjectKind: "Activity", subjectId: act.id, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { schoolId: input.schoolId, targetStaffId: target.staffId } });
  emitNotification({ userId: target.staffId, template: "plan.assignedByPL", channel: "Inbox", title: "New school support assigned by your PL", body: `${user.name} assigned ${TITLE[input.kind] ?? "an activity"}${input.schoolName ? ` at ${input.schoolName}` : ""} to you.`, href: "/plans" });
  revalidate(input.schoolId);
  return { ok: true, id: act.id };
}

// ── Reschedule (date move, reason, slip limit) ──────────────────────
export async function rescheduleActivity(id: string, newDateIso: string, reason: string): Promise<MyPlanResult> {
  if (await tryBackend(id, "reschedule", { scheduledDate: newDateIso, reason })) { revalidate(); return { ok: true, id }; }
  const a = findActivity(id);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  const user = await getCurrentUser();
  if (!canActOnActivity(user, a)) return { ok: false, reason: "FORBIDDEN", message: "You can only act on your own (or a supervised CCEO's) plan activities." };
  const count = a.rescheduleCount ?? 0;
  if (!canReschedule(count)) return { ok: false, reason: "SLIP_LIMIT" };
  updateActivity(id, {
    scheduledDate: newDateIso,
    rescheduleCount: count + 1,
    lastReason: reason,
    // a reschedule revives a deferred/cancelled item back into the plan
    status: a.status === "Deferred" || a.status === "Cancelled" ? "Planned" : a.status,
  });
  emitAudit({ action: "myplan.activity.rescheduled", subjectKind: "Activity", subjectId: id, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { reason, moveNo: count + 1 } });
  revalidate(a.schoolId);
  return { ok: true, id };
}

// ── Reassign (staff ↔ partner) ──────────────────────────────────────
export async function reassignActivity(id: string, delivery: "staff" | "partner", partnerName?: string): Promise<MyPlanResult> {
  if (await tryBackend(id, "reassign", { deliveryType: delivery })) { revalidate(); return { ok: true, id }; }
  const a = findActivity(id);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  const user = await getCurrentUser();
  if (!canActOnActivity(user, a)) return { ok: false, reason: "FORBIDDEN", message: "You can only act on your own (or a supervised CCEO's) plan activities." };
  updateActivity(id, { deliveryType: delivery, partnerName: delivery === "partner" ? partnerName : undefined });
  emitAudit({ action: "myplan.activity.reassigned", subjectKind: "Activity", subjectId: id, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { delivery, partnerName } });
  revalidate(a.schoolId);
  return { ok: true, id };
}

// ── Cancel / Defer (not happening now — distinct from a date move) ──
export async function cancelActivity(id: string, reason: string): Promise<MyPlanResult> {
  if (await tryBackend(id, "cancel", { reason })) { revalidate(); return { ok: true, id }; }
  const a = findActivity(id);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  const user = await getCurrentUser();
  if (!canActOnActivity(user, a)) return { ok: false, reason: "FORBIDDEN", message: "You can only act on your own (or a supervised CCEO's) plan activities." };
  updateActivity(id, { status: "Cancelled", lastReason: reason });
  emitAudit({ action: "myplan.activity.cancelled", subjectKind: "Activity", subjectId: id, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { reason } });
  revalidate(a.schoolId);
  return { ok: true, id };
}

export async function deferActivity(id: string, reason: string): Promise<MyPlanResult> {
  if (await tryBackend(id, "defer", { reason })) { revalidate(); return { ok: true, id }; }
  const a = findActivity(id);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  const user = await getCurrentUser();
  if (!canActOnActivity(user, a)) return { ok: false, reason: "FORBIDDEN", message: "You can only act on your own (or a supervised CCEO's) plan activities." };
  updateActivity(id, { status: "Deferred", lastReason: reason });
  emitAudit({ action: "myplan.activity.deferred", subjectKind: "Activity", subjectId: id, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { reason } });
  revalidate(a.schoolId);
  return { ok: true, id };
}

// ── Complete (simple path for the My Plan loop) ─────────────────────
export async function completeActivity(id: string, salesforceId?: string): Promise<MyPlanResult> {
  const a = findActivity(id);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  const user = await getCurrentUser();
  if (!canActOnActivity(user, a)) return { ok: false, reason: "FORBIDDEN", message: "You can only act on your own (or a supervised CCEO's) plan activities." };
  updateActivity(id, { status: "Completed", salesforceId: salesforceId?.trim() || a.salesforceId });
  emitAudit({ action: "myplan.activity.completed", subjectKind: "Activity", subjectId: id, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { salesforceId } });
  revalidate(a.schoolId);
  return { ok: true, id };
}
