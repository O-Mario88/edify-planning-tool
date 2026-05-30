"use server";

// W10 — Leave management server actions.
//
// State machine: Pending → Approved | Rejected | Cancelled.
//
// Integrity rule #9: Approved leave reduces the staff member's FWI
// capacity for the affected period. The `availableDaysFor` helper
// returns staff capacity inclusive of any Approved leave overlap so
// the workload + performance engines pick it up the next time they
// recompute.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";
import {
  type LeaveKind,
  type LeaveRecord,
  type LeaveStatus,
  findLeaveRecord,
  leaveRecords as leaveRecordsStore,
  newId,
  updateLeaveRecord,
} from "./store";

export type LeaveActionResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_STATE"; current: LeaveStatus }
  | { ok: false; reason: "INVALID_INPUT"; field: string };

const APPROVER_ROLES = new Set(["HumanResource", "CountryDirector", "CountryProgramLead", "Admin"]);
const STAFF_ALLOWED  = new Set(["CCEO", "CountryProgramLead", "ImpactAssessment", "ProgramAccountant", "HumanResource", "Admin"]);

// ─── 1. requestLeave ───────────────────────────────────────────────

export async function requestLeave(input: {
  kind: LeaveKind;
  startDate: string;          // YYYY-MM-DD
  endDate: string;            // YYYY-MM-DD inclusive
  reason?: string;
}): Promise<LeaveActionResult & { days?: number }> {
  const user = await getCurrentUser();
  if (!STAFF_ALLOWED.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input.startDate)) {
    return { ok: false, reason: "INVALID_INPUT", field: "startDate" };
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input.endDate)) {
    return { ok: false, reason: "INVALID_INPUT", field: "endDate" };
  }
  const days = dayCountInclusive(input.startDate, input.endDate);
  if (days <= 0) return { ok: false, reason: "INVALID_INPUT", field: "endDate" };
  // Sanity ceiling — 90 days in one request flagged as malformed.
  if (days > 90) return { ok: false, reason: "INVALID_INPUT", field: "endDate" };

  const row: LeaveRecord = {
    id: newId("lv"),
    staffId: user.staffId,
    staffName: user.name,
    kind: input.kind,
    startDate: input.startDate,
    endDate: input.endDate,
    days,
    reason: input.reason,
    status: "Pending",
    createdAt: new Date().toISOString(),
  };
  leaveRecordsStore().push(row);

  emitAudit({
    action: "leave.requested",
    subjectKind: "LeaveRecord",
    subjectId: row.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { kind: input.kind, days, startDate: input.startDate, endDate: input.endDate },
  });
  emitNotificationFanOut(["HR", "PROGRAM_LEAD"], {
    template: "leave.requested",
    channel: "Inbox",
    title: `${user.name} requested ${days} day${days === 1 ? "" : "s"} of ${input.kind} leave`,
    body: `${input.startDate} → ${input.endDate}${input.reason ? ` · "${input.reason.slice(0, 60)}"` : ""}`,
    href: `/leave`,
  });
  revalidateLeaveSurfaces();
  return { ok: true, id: row.id, days };
}

// ─── 2. approveLeave ───────────────────────────────────────────────

export async function approveLeave(leaveId: string): Promise<LeaveActionResult> {
  const user = await getCurrentUser();
  if (!APPROVER_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const l = findLeaveRecord(leaveId);
  if (!l) return { ok: false, reason: "NOT_FOUND" };
  if (l.status !== "Pending") return { ok: false, reason: "INVALID_STATE", current: l.status };

  updateLeaveRecord(leaveId, {
    status: "Approved",
    approvedAt: new Date().toISOString(),
    approvedById: user.staffId,
  });
  emitAudit({
    action: "leave.approved",
    subjectKind: "LeaveRecord",
    subjectId: leaveId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { days: l.days, kind: l.kind },
  });
  emitNotificationFanOut([l.staffId], {
    template: "leave.approved",
    channel: "Inbox",
    title: "Leave approved",
    body: `Your ${l.days}-day ${l.kind} leave (${l.startDate} → ${l.endDate}) is approved.`,
    href: `/leave`,
  });
  revalidateLeaveSurfaces();
  return { ok: true, id: leaveId };
}

// ─── 3. rejectLeave ────────────────────────────────────────────────

export async function rejectLeave(
  leaveId: string,
  reason: string,
): Promise<LeaveActionResult> {
  const user = await getCurrentUser();
  if (!APPROVER_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!reason || reason.trim().length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }
  const l = findLeaveRecord(leaveId);
  if (!l) return { ok: false, reason: "NOT_FOUND" };
  if (l.status !== "Pending") return { ok: false, reason: "INVALID_STATE", current: l.status };

  updateLeaveRecord(leaveId, { status: "Rejected" });
  emitAudit({
    action: "leave.rejected",
    subjectKind: "LeaveRecord",
    subjectId: leaveId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { reason: reason.trim() },
  });
  emitNotificationFanOut([l.staffId], {
    template: "leave.rejected",
    channel: "Inbox",
    title: "Leave request rejected",
    body: reason.trim(),
    href: `/leave`,
  });
  revalidateLeaveSurfaces();
  return { ok: true, id: leaveId };
}

// ─── 4. cancelLeave ────────────────────────────────────────────────

export async function cancelLeave(leaveId: string): Promise<LeaveActionResult> {
  const user = await getCurrentUser();
  const l = findLeaveRecord(leaveId);
  if (!l) return { ok: false, reason: "NOT_FOUND" };
  // Staff can cancel their own pending or approved request before it
  // starts; approvers can cancel anyone's.
  const isOwnFuture = l.staffId === user.staffId && new Date(l.startDate).getTime() > Date.now();
  if (!isOwnFuture && !APPROVER_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (l.status !== "Pending" && l.status !== "Approved") {
    return { ok: false, reason: "INVALID_STATE", current: l.status };
  }
  updateLeaveRecord(leaveId, { status: "Cancelled" });
  emitAudit({
    action: "leave.cancelled",
    subjectKind: "LeaveRecord",
    subjectId: leaveId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  revalidateLeaveSurfaces();
  return { ok: true, id: leaveId };
}

// ─── 5. availableDaysFor (helper — FWI uses this) ──────────────────
//
// Returns the leave-adjusted available working days for a staff in a
// given window. Integrity rule #9: approved leave subtracts capacity.
// Pure read on the store, no side effects.

export async function availableDaysFor(
  staffId: string,
  totalDaysInPeriod: number,
  periodStartIso: string,
  periodEndIso: string,
): Promise<{ available: number; approvedLeaveDays: number }> {
  const periodStart = new Date(periodStartIso).getTime();
  const periodEnd   = new Date(periodEndIso).getTime();
  let approvedLeaveDays = 0;
  for (const l of leaveRecordsStore()) {
    if (l.staffId !== staffId) continue;
    if (l.status !== "Approved") continue;
    const s = new Date(l.startDate).getTime();
    const e = new Date(l.endDate).getTime();
    if (e < periodStart || s > periodEnd) continue;
    // Days inside the period only.
    const overlapStart = Math.max(s, periodStart);
    const overlapEnd   = Math.min(e, periodEnd);
    approvedLeaveDays += Math.round((overlapEnd - overlapStart) / 86_400_000) + 1;
  }
  return { available: Math.max(totalDaysInPeriod - approvedLeaveDays, 0), approvedLeaveDays };
}

function dayCountInclusive(startIso: string, endIso: string): number {
  const s = new Date(startIso).getTime();
  const e = new Date(endIso).getTime();
  if (!Number.isFinite(s) || !Number.isFinite(e) || e < s) return 0;
  return Math.round((e - s) / 86_400_000) + 1;
}

function revalidateLeaveSurfaces() {
  try {
    revalidatePath("/leave");
    revalidatePath("/calendar");
    revalidatePath("/dashboards/hr");
    revalidatePath("/team-targets");
    revalidatePath("/my-targets");
    revalidatePath("/notifications");
  } catch { /* outside request */ }
}
