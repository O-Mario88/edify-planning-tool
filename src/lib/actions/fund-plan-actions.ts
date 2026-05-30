"use server";

// Fund-plan approve / return server actions — the canonical Bucket C
// reference implementation. Copy this shape for every other mutation:
//
//   1. Mark "use server".
//   2. Resolve actor via `getCurrentUser` (NEVER trust an actor param).
//   3. Validate role + input with explicit guards.
//   4. Read + mutate the store in one step (no torn writes).
//   5. Emit ONE audit row per state transition.
//   6. Emit notifications to anyone the workflow says is next.
//   7. revalidatePath every URL that displays this entity.
//   8. Return a discriminated union — never throw on expected outcomes.
//
// Today the store is the in-memory `fundApprovalQueue` array. When the
// Prisma swap lands, the only change inside this file is replacing the
// array mutation with `prisma.weeklyFundRequest.update(...)` inside a
// `prisma.$transaction([])` that also writes the AuditEvent +
// Notification rows produced by `emitAudit` / `emitNotification`.

import { revalidatePath } from "next/cache";
import { fundApprovalQueue, type FundApprovalItem } from "@/lib/fund-approvals-mock";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";

// ─── Result type ────────────────────────────────────────────────────
//
// Discriminated union so the caller can `switch (res.reason)` for
// targeted UI. NEVER return `{ ok: false, error: string }` — string
// errors are unsafe to typecheck against.

export type FundPlanActionResult =
  | { ok: true; id: string; newStatus: FundApprovalItem["status"] }
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_STATE"; current: FundApprovalItem["status"] }
  | { ok: false; reason: "INVALID_INPUT"; field: string };

// ─── Authorisation ──────────────────────────────────────────────────
//
// `/approvals` is gated by middleware + page-level guard, but defence
// in depth — the server action revalidates the role itself, because
// server actions can be invoked from any client surface, not just the
// pages where we render them.

const APPROVE_ROLES = new Set([
  "CountryProgramLead",
  "CountryDirector",
  "RVP",
  "ProgramAccountant",
  "Admin",
]);

// Return path is the same set: anyone who can approve can also return
// for correction (with a stated reason).
const RETURN_ROLES = APPROVE_ROLES;

// Recipients of an approval/return notification: always the CCEO who
// owns the plan. In a real DB we'd join queueRow.requesterId → User.
// For now we map by `initials` since the mock queue uses that as the
// stable identifier.
function recipientsFor(item: FundApprovalItem): string[] {
  return [item.initials]; // staffId proxy in mock-land
}

// ─── approveFundPlan ────────────────────────────────────────────────

export async function approveFundPlan(planId: string): Promise<FundPlanActionResult> {
  const user = await getCurrentUser();
  if (!APPROVE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const idx = fundApprovalQueue.findIndex((p) => p.id === planId);
  if (idx === -1) return { ok: false, reason: "NOT_FOUND" };

  const current = fundApprovalQueue[idx];
  // The only valid sources for an approval are "Awaiting Approval" /
  // "Needs Review" / "Awaiting Review". Approving a Ready or Returned
  // plan is a no-op the UI should never offer.
  const approvable: ReadonlySet<FundApprovalItem["status"]> = new Set([
    "Awaiting Approval",
    "Needs Review",
    "Awaiting Review",
  ]);
  if (!approvable.has(current.status)) {
    return { ok: false, reason: "INVALID_STATE", current: current.status };
  }

  const newStatus: FundApprovalItem["status"] = "Ready";
  fundApprovalQueue[idx] = { ...current, status: newStatus };

  emitAudit({
    action: "fundPlan.approved",
    subjectKind: "FundApprovalItem",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { previousStatus: current.status, newStatus, amount: current.amount },
  });

  emitNotificationFanOut(recipientsFor(current), {
    template: "fundPlan.approved",
    channel: "Inbox",
    title: `${current.cceoName}'s ${current.amount} plan is approved`,
    body: `${user.name} approved your fund plan. Funds will be queued for disbursement.`,
    href: `/approvals?plan=${planId}`,
  });

  // Every surface that shows this plan's status must re-render.
  revalidateAllApprovalSurfaces();

  return { ok: true, id: planId, newStatus };
}

// ─── returnFundPlan ────────────────────────────────────────────────

export async function returnFundPlan(
  planId: string,
  reason: string,
): Promise<FundPlanActionResult> {
  const user = await getCurrentUser();
  if (!RETURN_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  // Reason is required (and meaningful) so the audit trail is useful
  // and so the CCEO knows what to fix.
  const trimmed = reason?.trim() ?? "";
  if (trimmed.length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }

  const idx = fundApprovalQueue.findIndex((p) => p.id === planId);
  if (idx === -1) return { ok: false, reason: "NOT_FOUND" };
  const current = fundApprovalQueue[idx];

  // Returns are only valid from a pre-approval state.
  const returnable: ReadonlySet<FundApprovalItem["status"]> = new Set([
    "Awaiting Approval",
    "Needs Review",
    "Awaiting Review",
  ]);
  if (!returnable.has(current.status)) {
    return { ok: false, reason: "INVALID_STATE", current: current.status };
  }

  const newStatus: FundApprovalItem["status"] = "Returned";
  fundApprovalQueue[idx] = { ...current, status: newStatus };

  emitAudit({
    action: "fundPlan.returned",
    subjectKind: "FundApprovalItem",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { previousStatus: current.status, newStatus, reason: trimmed, amount: current.amount },
  });

  emitNotificationFanOut(recipientsFor(current), {
    template: "fundPlan.returned",
    channel: "Inbox",
    title: `${current.cceoName}'s ${current.amount} plan was returned`,
    body: `${user.name} returned your plan: "${trimmed}"`,
    href: `/approvals?plan=${planId}`,
  });

  revalidateAllApprovalSurfaces();

  return { ok: true, id: planId, newStatus };
}

// ─── revalidation fan-out ──────────────────────────────────────────
//
// Every URL where the affected plan's status is visible. Pull this
// list into a single helper so adding a new dashboard tile doesn't
// require touching every action.

function revalidateAllApprovalSurfaces() {
  // try/catch because server actions may be invoked outside an HTTP
  // request scope (unit tests, scheduled jobs) — revalidatePath
  // throws if there's no context.
  try {
    revalidatePath("/approvals");
    revalidatePath("/dashboards/cpl");
    revalidatePath("/dashboards/director");
    revalidatePath("/dashboards/accountant");
    revalidatePath("/dashboards/cceo");
    revalidatePath("/notifications");
  } catch {
    /* outside request — fine */
  }
}
