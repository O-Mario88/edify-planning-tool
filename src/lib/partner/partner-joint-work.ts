// Joint Work Mode helpers.
//
// The spec is explicit about who-owns-what when partner + Edify staff
// collaborate. These helpers centralise the rules so UIs don't
// reproduce the logic ad-hoc.
//
// Rules:
//   • Exactly one responsibility owner (closes the activity)
//   • Exactly one next-action owner (may differ from responsibility)
//   • Lead organization is resolved from the JointWorkLead field —
//     not inferred from who has more assignments
//   • Shared checklist items can be marked done by either side; the
//     done-by user is recorded for audit

import type {
  JointWorkAssignment,
  JointWorkLead,
  JointWorkRole,
} from "./partner-types";

// ────────── Ownership resolution ──────────

export type Owner = { userId: string; userName: string; side: "Edify" | "Partner" };

export function responsibilityOwner(jw: JointWorkAssignment): Owner | null {
  return findOwner(jw, jw.responsibilityOwnerUserId);
}

export function nextActionOwner(jw: JointWorkAssignment): Owner | null {
  return findOwner(jw, jw.nextActionOwnerUserId);
}

function findOwner(jw: JointWorkAssignment, userId: string): Owner | null {
  const edify = jw.edifyAssignments.find((a) => a.userId === userId);
  if (edify) return { userId, userName: edify.userName, side: "Edify" };
  const partner = jw.partnerAssignments.find((a) => a.userId === userId);
  if (partner) return { userId, userName: partner.userName, side: "Partner" };
  return null;
}

// ────────── Role helpers ──────────

export function rolesFor(jw: JointWorkAssignment, userId: string): JointWorkRole[] {
  return [
    ...jw.edifyAssignments.filter((a) => a.userId === userId).map((a) => a.role),
    ...jw.partnerAssignments.filter((a) => a.userId === userId).map((a) => a.role),
  ];
}

export function isLeadFor(jw: JointWorkAssignment, userId: string): boolean {
  return rolesFor(jw, userId).includes("Lead");
}

// ────────── Lead-side resolver ──────────
//
// Useful for UIs that show "Lead: Partner" / "Lead: Edify" without
// having to enumerate every assignment.

export function leadSide(jw: JointWorkAssignment): JointWorkLead {
  return jw.lead;
}

// ────────── Checklist progress ──────────

export function checklistProgress(jw: JointWorkAssignment): { done: number; total: number; pct: number } {
  const total = jw.sharedChecklist.length;
  const done = jw.sharedChecklist.filter((c) => c.done).length;
  return { done, total, pct: total === 0 ? 0 : Math.round((done / total) * 100) };
}

// ────────── Validation ──────────
//
// Returns an error string if the joint-work assignment is malformed.
// Called at write time to keep the data layer clean.

export function validateJointWork(jw: JointWorkAssignment): string | null {
  if (jw.edifyAssignments.length === 0 && jw.partnerAssignments.length === 0) {
    return "Joint work needs at least one Edify or Partner assignee.";
  }
  // Responsibility owner must exist on one side.
  if (!responsibilityOwner(jw)) {
    return "Responsibility owner is not in the assignment list.";
  }
  // Next-action owner must exist on one side.
  if (!nextActionOwner(jw)) {
    return "Next-action owner is not in the assignment list.";
  }
  // Lead side must have at least one assignee marked Lead role.
  if (jw.lead === "Edify" && !jw.edifyAssignments.some((a) => a.role === "Lead")) {
    return "Lead is Edify but no Edify assignee has role Lead.";
  }
  if (jw.lead === "Partner" && !jw.partnerAssignments.some((a) => a.role === "Lead")) {
    return "Lead is Partner but no Partner assignee has role Lead.";
  }
  return null;
}
