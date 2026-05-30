// Cross-component assignment store.
//
// When a Country Program Lead clicks "Assign" on a Training Follow-Up
// row, the assignment is persisted here (localStorage) keyed by the
// receiving CCEO's staffId. The CCEO's My Targets view reads from the
// same store on render so the assignment lands in their plan / todo
// list immediately — no round-trip through a server, no rebuild.
//
// In production this is a server-side `assignments` table written by
// the PL's "Assign" mutation and read by the CCEO's todo selector.
// The shape below matches the future DB row 1:1 so swapping in a real
// backend doesn't touch the consumer UI.

"use client";

export type AssignmentUrgency = "Medium" | "High" | "Critical";

export type FollowUpAssignment = {
  // Stable id — uses the upstream alert id when available so re-assigns
  // are idempotent (clicking "Assign" twice doesn't create a duplicate
  // todo on the CCEO's plan).
  id: string;
  alertId: string;
  schoolId: string;
  schoolName: string;
  district: string;
  cluster?: string;
  urgency: AssignmentUrgency;
  daysSinceTraining: number;
  recommendedAction: string;
  // Receiving CCEO
  assignedToCceoId: string;
  assignedToCceoName: string;
  // Assigning PL
  assignedByName: string;
  // ISO timestamp for sorting + display
  assignedAt: string;
  // ISO date (YYYY-MM-DD) — the deadline the PL set when assigning.
  // Optional for backward compatibility with pre-deadline assignments.
  dueDate?: string;
  // Optional PL note attached to the assignment ("urgent — partner
  // visit next week" etc.). Renders on the CCEO row.
  note?: string;
  // Source surface — namespaces future assignment types (SSA refresh,
  // schools-needing-SSA, special-projects intake, etc.).
  source: "training-follow-up";
  // Per-CCEO state. Defaults to "open" on save; flipping to "completed"
  // happens when the CCEO captures a Salesforce ID for the visit.
  status: "open" | "completed";
  // Set when status flips to "completed". Records *why* (acknowledged
  // manually vs auto-closed by Salesforce ID capture).
  completedAt?: string;
  completedReason?: "salesforce-id-captured" | "acknowledged" | "supervisor-dismissed";
  completedSalesforceId?: string;
};

const KEY = "edify.assignments.v1";

function readAll(): FollowUpAssignment[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as FollowUpAssignment[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(list: FollowUpAssignment[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* localStorage full or disabled — silent in demo */
  }
}

// All assignments across all CCEOs. Used by admin / debug surfaces only.
export function loadAssignments(): FollowUpAssignment[] {
  return readAll();
}

// Assignments destined for a specific CCEO. Returned newest-first so the
// CCEO's todo list shows the most recently received item at the top.
export function loadAssignmentsForCceo(cceoStaffId: string): FollowUpAssignment[] {
  return readAll()
    .filter((a) => a.assignedToCceoId === cceoStaffId)
    .sort((a, b) => (a.assignedAt < b.assignedAt ? 1 : -1));
}

// Save (idempotent by `id`).
export function saveAssignment(a: FollowUpAssignment): void {
  const list = readAll();
  const idx = list.findIndex((x) => x.id === a.id);
  if (idx >= 0) list[idx] = a;
  else list.unshift(a);
  writeAll(list);
}

// Mark a single assignment complete with an explicit reason. Used by:
//   • the CCEO's "Add to plan" acknowledgement button
//   • the Salesforce-completion auto-closer (see closeAssignmentsBySchoolId)
//   • supervisor dismissal flows (future)
export function markAssignmentCompleted(
  id: string,
  reason: NonNullable<FollowUpAssignment["completedReason"]> = "acknowledged",
  meta?: { salesforceId?: string },
): void {
  const list = readAll();
  const idx = list.findIndex((x) => x.id === id);
  if (idx < 0) return;
  list[idx] = {
    ...list[idx],
    status: "completed",
    completedAt: new Date().toISOString(),
    completedReason: reason,
    completedSalesforceId: meta?.salesforceId,
  };
  writeAll(list);
}

// Auto-close any OPEN assignments that match the given (cceo, school)
// pair when the CCEO captures a Salesforce ID for that school. Returns
// the number of assignments closed so the caller can surface a toast
// ("Closed 1 PL follow-up assignment").
//
// This is the loop-closure pattern: the PL doesn't have to chase the
// CCEO; the CCEO doesn't have to remember which PL follow-up matches
// the visit they just logged. The Salesforce ID itself is the trigger.
export function closeAssignmentsBySchoolId(args: {
  cceoStaffId: string;
  schoolId: string;
  salesforceId: string;
}): number {
  const list = readAll();
  let closed = 0;
  const next = list.map((a) => {
    if (
      a.status === "open" &&
      a.assignedToCceoId === args.cceoStaffId &&
      a.schoolId === args.schoolId
    ) {
      closed += 1;
      return {
        ...a,
        status: "completed" as const,
        completedAt: new Date().toISOString(),
        completedReason: "salesforce-id-captured" as const,
        completedSalesforceId: args.salesforceId,
      };
    }
    return a;
  });
  if (closed > 0) writeAll(next);
  return closed;
}

export function clearAssignment(id: string): void {
  writeAll(readAll().filter((x) => x.id !== id));
}

// Helper for deadline display. Returns a tone + label tuple based on
// how the due date compares to today. Centralized so PL and CCEO
// surfaces colorize the same way.
export function deadlineState(
  dueDate: string | undefined,
  todayIso: string = new Date().toISOString().slice(0, 10),
): { tone: "rose" | "amber" | "muted" | "none"; label: string; daysLeft: number | null } {
  if (!dueDate) return { tone: "none", label: "", daysLeft: null };
  const due = new Date(`${dueDate}T00:00:00`);
  const today = new Date(`${todayIso}T00:00:00`);
  const diffMs = due.getTime() - today.getTime();
  const days = Math.round(diffMs / 86_400_000);
  if (days < 0) return { tone: "rose", label: `Overdue by ${Math.abs(days)}d`, daysLeft: days };
  if (days === 0) return { tone: "rose", label: "Due today", daysLeft: 0 };
  if (days <= 2) return { tone: "amber", label: `Due in ${days}d`, daysLeft: days };
  if (days <= 7) return { tone: "muted", label: `Due in ${days}d`, daysLeft: days };
  return { tone: "muted", label: `Due ${dueDate}`, daysLeft: days };
}
