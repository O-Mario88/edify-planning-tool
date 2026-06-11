"use server";

// W3 — Plan lifecycle server actions.
//
// State machine:
//   Draft → SubmittedForApproval → Approved → Active → Closed
//          ↘ Returned (Draft loop)
//
// Approving a plan triggers W5 auto-generation of weekly fund
// requests. We import that helper at the top so the cross-workflow
// contract is explicit and the dependency graph is acyclic
// (plan → weekly-fund, never the reverse).

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotification, emitNotificationFanOut } from "./audit";
import {
  type ActivityKind,
  type PlanRecord,
  type PlannedActivityRecord,
  type PlannedActivityStatus,
  type PlanStatus,
  activities as activitiesStore,
  claimIdempotencyKey,
  findActivity,
  findPlan,
  newId,
  plans as plansStore,
  updateActivity as updateActivityRow,
  updatePlan,
} from "./store";
import { generateWeeklyFundRequestsForPlan } from "./weekly-fund-actions";

// ─── Result types ───────────────────────────────────────────────────

export type PlanActionResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_STATE"; current: PlanStatus | PlannedActivityStatus }
  | { ok: false; reason: "INVALID_INPUT"; field: string }
  | { ok: false; reason: "DUPLICATE" };

// ─── Authorisation maps ─────────────────────────────────────────────

const CCEO_OWN_PLAN_ROLES = new Set(["CCEO", "Admin"]);
const PLAN_REVIEWER_ROLES = new Set([
  "CountryProgramLead",
  "CountryDirector",
  "Admin",
]);

// CCEOs may only act on plans they author. Reviewers (PL/CD) may act
// on plans within their country scope. Centralised so every action
// applies the rule the same way.
function canEditOwnPlan(actorRole: string, actorId: string, plan: PlanRecord): boolean {
  if (actorRole === "Admin") return true;
  if (!CCEO_OWN_PLAN_ROLES.has(actorRole)) return false;
  return plan.authorId === actorId;
}

// ─── 1. createPlan ──────────────────────────────────────────────────

export async function createPlan(monthIso: string): Promise<PlanActionResult> {
  const user = await getCurrentUser();
  if (!CCEO_OWN_PLAN_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  // Month must look like "YYYY-MM" — the simplest check that catches
  // most typos without pulling a date library in.
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(monthIso)) {
    return { ok: false, reason: "INVALID_INPUT", field: "monthIso" };
  }
  // Schema constraint @@unique([authorId, monthIso]) — enforce it now
  // so the swap to Postgres doesn't surface a runtime constraint error.
  if (plansStore().some((p) => p.authorId === user.staffId && p.monthIso === monthIso)) {
    return { ok: false, reason: "DUPLICATE" };
  }
  const now = new Date().toISOString();
  const plan: PlanRecord = {
    id: newId("plan"),
    authorId: user.staffId,
    authorName: user.name,
    countryId: "Uganda", // single-country MVP; resolved from user in prod
    monthIso,
    status: "Draft",
    totalCostCents: 0,
    createdAt: now,
    updatedAt: now,
  };
  plansStore().push(plan);

  emitAudit({
    action: "plan.created",
    subjectKind: "Plan",
    subjectId: plan.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { monthIso },
  });

  revalidatePlanSurfaces();
  return { ok: true, id: plan.id };
}

// ─── 2. addActivityToPlan ──────────────────────────────────────────

export type DraftActivity = {
  kind:             ActivityKind;
  title:            string;
  weekOfMonth:      number;
  scheduledDate?:   string;
  schoolId?:        string;
  assigneeId?:      string;
  estCostCents:     number;
  interventionArea?: string;
};

export async function addActivityToPlan(
  planId: string,
  draft: DraftActivity,
): Promise<PlanActionResult> {
  const user = await getCurrentUser();
  const plan = findPlan(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (!canEditOwnPlan(user.role, user.staffId, plan)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  // Edits allowed only while the plan is Draft or Returned.
  if (plan.status !== "Draft" && plan.status !== "Returned") {
    return { ok: false, reason: "INVALID_STATE", current: plan.status };
  }
  if (!draft.title || draft.title.trim().length < 3) {
    return { ok: false, reason: "INVALID_INPUT", field: "title" };
  }
  if (draft.weekOfMonth < 1 || draft.weekOfMonth > 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "weekOfMonth" };
  }
  if (draft.estCostCents < 0) {
    return { ok: false, reason: "INVALID_INPUT", field: "estCostCents" };
  }

  const now = new Date().toISOString();
  const activity: PlannedActivityRecord = {
    id: newId("act"),
    planId,
    kind: draft.kind,
    title: draft.title.trim(),
    weekOfMonth: draft.weekOfMonth,
    scheduledDate: draft.scheduledDate,
    schoolId: draft.schoolId,
    assigneeId: draft.assigneeId ?? user.staffId,
    estCostCents: draft.estCostCents,
    status: "Planned",
    interventionArea: draft.interventionArea,
    createdAt: now,
    updatedAt: now,
  };
  activitiesStore().push(activity);
  recomputePlanTotal(planId);

  emitAudit({
    action: "plan.activity.added",
    subjectKind: "Plan",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { activityId: activity.id, title: activity.title, estCostCents: draft.estCostCents },
  });

  revalidatePlanSurfaces(planId);
  return { ok: true, id: activity.id };
}

// ─── 2b. createPlanWithActivities (Plan Builder finalize) ───────────
//
// One-shot used by the Plan Builder "Finalize plan" CTA: take the
// accumulated activity batches, create (or reuse this author's open
// Draft/Returned plan for the month), persist every activity, recompute
// the cached total, and optionally submit for approval. Wrapping it in a
// single action keeps the builder from orchestrating N round-trips and
// gives one audit trail per finalize. In production this is one
// `prisma.$transaction([...])`.

export async function createPlanWithActivities(
  monthIso: string,
  drafts: DraftActivity[],
  opts?: { submit?: boolean },
): Promise<PlanActionResult & { activityCount?: number; submitted?: boolean }> {
  const user = await getCurrentUser();
  if (!CCEO_OWN_PLAN_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(monthIso)) {
    return { ok: false, reason: "INVALID_INPUT", field: "monthIso" };
  }
  if (!Array.isArray(drafts) || drafts.length === 0) {
    return { ok: false, reason: "INVALID_INPUT", field: "drafts" };
  }

  // A submitted/approved plan for this month is locked — can't append.
  const locked = plansStore().some(
    (p) => p.authorId === user.staffId && p.monthIso === monthIso && p.status !== "Draft" && p.status !== "Returned",
  );
  if (locked) return { ok: false, reason: "DUPLICATE" };

  const now = new Date().toISOString();
  let plan = plansStore().find(
    (p) => p.authorId === user.staffId && p.monthIso === monthIso && (p.status === "Draft" || p.status === "Returned"),
  );
  if (!plan) {
    plan = {
      id: newId("plan"),
      authorId: user.staffId,
      authorName: user.name,
      countryId: "Uganda",
      monthIso,
      status: "Draft",
      totalCostCents: 0,
      createdAt: now,
      updatedAt: now,
    };
    plansStore().push(plan);
    emitAudit({
      action: "plan.created",
      subjectKind: "Plan",
      subjectId: plan.id,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: { monthIso, via: "planBuilder" },
    });
  }

  let added = 0;
  for (const d of drafts) {
    if (!d.title || d.title.trim().length < 3) continue;
    const week = d.weekOfMonth >= 1 && d.weekOfMonth <= 5 ? d.weekOfMonth : 1;
    activitiesStore().push({
      id: newId("act"),
      planId: plan.id,
      kind: d.kind,
      title: d.title.trim(),
      weekOfMonth: week,
      scheduledDate: d.scheduledDate,
      schoolId: d.schoolId,
      assigneeId: d.assigneeId ?? user.staffId,
      estCostCents: Math.max(0, Math.round(d.estCostCents)),
      status: "Planned",
      interventionArea: d.interventionArea,
      createdAt: now,
      updatedAt: now,
    });
    added++;
  }
  if (added === 0) return { ok: false, reason: "INVALID_INPUT", field: "drafts" };
  recomputePlanTotal(plan.id);

  emitAudit({
    action: "plan.activities.bulkAdded",
    subjectKind: "Plan",
    subjectId: plan.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { count: added, monthIso, via: "planBuilder" },
  });

  let submitted = false;
  if (opts?.submit && (plan.status === "Draft" || plan.status === "Returned")) {
    updatePlan(plan.id, { status: "SubmittedForApproval", submittedAt: now });
    submitted = true;
    const fresh = findPlan(plan.id);
    emitAudit({
      action: "plan.submitted",
      subjectKind: "Plan",
      subjectId: plan.id,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: { totalCostCents: fresh?.totalCostCents ?? 0, via: "planBuilder" },
    });
    emitNotification({
      userId: "PROGRAM_LEAD",
      template: "plan.submitted",
      channel: "Inbox",
      title: `${user.name} submitted ${monthIso} plan for approval`,
      body: `${added} activities · total ${((fresh?.totalCostCents ?? 0) / 100).toLocaleString()} UGX.`,
      href: `/approvals?plan=${plan.id}`,
    });
  }

  revalidatePlanSurfaces(plan.id);
  return { ok: true, id: plan.id, activityCount: added, submitted };
}

// ─── 3. updateActivity ──────────────────────────────────────────────

export async function updateActivity(
  activityId: string,
  patch: Partial<DraftActivity>,
): Promise<PlanActionResult> {
  const user = await getCurrentUser();
  const activity = findActivity(activityId);
  if (!activity) return { ok: false, reason: "NOT_FOUND" };
  const plan = findPlan(activity.planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (!canEditOwnPlan(user.role, user.staffId, plan)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (plan.status !== "Draft" && plan.status !== "Returned") {
    return { ok: false, reason: "INVALID_STATE", current: plan.status };
  }
  if (patch.weekOfMonth != null && (patch.weekOfMonth < 1 || patch.weekOfMonth > 5)) {
    return { ok: false, reason: "INVALID_INPUT", field: "weekOfMonth" };
  }
  if (patch.estCostCents != null && patch.estCostCents < 0) {
    return { ok: false, reason: "INVALID_INPUT", field: "estCostCents" };
  }

  // Detect a reschedule that crosses a week boundary before the patch
  // is applied so we can recalc the weekly fund request afterwards
  // (punch-list B11 — was specced but never wired). A reschedule is
  // either an explicit weekOfMonth change OR a scheduledDate change
  // whose ISO falls in a different calendar week.
  const oldWeek      = activity.weekOfMonth;
  const oldDateIso   = activity.scheduledDate;
  const updated = updateActivityRow(activityId, patch);
  if (!updated) return { ok: false, reason: "NOT_FOUND" };
  recomputePlanTotal(plan.id);

  emitAudit({
    action: "plan.activity.updated",
    subjectKind: "Plan",
    subjectId: plan.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { activityId, patch },
  });

  const newWeek    = updated.weekOfMonth;
  const newDateIso = updated.scheduledDate;
  const weekChanged = newWeek !== oldWeek;
  const dateCrossedWeek =
    !!oldDateIso && !!newDateIso && oldDateIso !== newDateIso &&
    isoCalendarWeek(oldDateIso) !== isoCalendarWeek(newDateIso);
  if (weekChanged || dateCrossedWeek) {
    // Fire-and-forget — recalc never blocks the user's reschedule.
    // The generator regenerates / upserts the affected weekly fund
    // requests and revalidates the fund surfaces itself.
    void generateWeeklyFundRequestsForPlan(plan.id).catch(() => {});
  }

  revalidatePlanSurfaces(plan.id);
  return { ok: true, id: activityId };
}

/** ISO calendar-week key — used to detect a reschedule that
 *  crosses a week boundary so the MFR can recalc (B11). */
function isoCalendarWeek(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // Move to nearest Thursday: current date + 4 - current day number
  // (ISO weeks start Monday).
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((+t - +yearStart) / 86_400_000 + 1) / 7);
  return `${t.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

// ─── 4. removeActivity ──────────────────────────────────────────────

export async function removeActivity(activityId: string): Promise<PlanActionResult> {
  const user = await getCurrentUser();
  const activity = findActivity(activityId);
  if (!activity) return { ok: false, reason: "NOT_FOUND" };
  const plan = findPlan(activity.planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (!canEditOwnPlan(user.role, user.staffId, plan)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (plan.status !== "Draft" && plan.status !== "Returned") {
    return { ok: false, reason: "INVALID_STATE", current: plan.status };
  }
  const store = activitiesStore();
  const idx = store.findIndex((a) => a.id === activityId);
  if (idx === -1) return { ok: false, reason: "NOT_FOUND" };
  store.splice(idx, 1);
  recomputePlanTotal(plan.id);

  emitAudit({
    action: "plan.activity.removed",
    subjectKind: "Plan",
    subjectId: plan.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { activityId, title: activity.title },
  });

  revalidatePlanSurfaces(plan.id);
  return { ok: true, id: activityId };
}

// ─── 5. submitPlan (Draft → SubmittedForApproval) ──────────────────

export async function submitPlan(planId: string): Promise<PlanActionResult> {
  const user = await getCurrentUser();
  const plan = findPlan(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (!canEditOwnPlan(user.role, user.staffId, plan)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (plan.status !== "Draft" && plan.status !== "Returned") {
    return { ok: false, reason: "INVALID_STATE", current: plan.status };
  }
  // Empty plans can't be submitted.
  if (activitiesStore().filter((a) => a.planId === planId).length === 0) {
    return { ok: false, reason: "INVALID_INPUT", field: "activities" };
  }

  const now = new Date().toISOString();
  updatePlan(planId, { status: "SubmittedForApproval", submittedAt: now });

  emitAudit({
    action: "plan.submitted",
    subjectKind: "Plan",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { previousStatus: plan.status, totalCostCents: plan.totalCostCents },
  });
  // Notify the CountryProgramLead. In production this fans out to all
  // active PLs in the country; mock-mode emits a single inbox row.
  emitNotification({
    userId: "PROGRAM_LEAD",
    template: "plan.submitted",
    channel: "Inbox",
    title: `${plan.authorName} submitted ${plan.monthIso} plan for approval`,
    body: `Total: ${(plan.totalCostCents / 100).toLocaleString()} UGX across ${activitiesStore().filter(a => a.planId === planId).length} activities.`,
    href: `/approvals?plan=${planId}`,
  });

  revalidatePlanSurfaces(planId);
  return { ok: true, id: planId };
}

// ─── 6. approvePlan ─────────────────────────────────────────────────
//
// SubmittedForApproval → Approved, then immediately fires W5
// auto-generation. Both writes happen in the same logical step; if
// W5 fails, the plan still moves to Approved (the engine result is
// preserved as an audit payload so the CPL sees what went wrong).

export async function approvePlan(planId: string): Promise<PlanActionResult & { generatedRequestIds?: string[] }> {
  const user = await getCurrentUser();
  if (!PLAN_REVIEWER_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const plan = findPlan(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (plan.status !== "SubmittedForApproval") {
    return { ok: false, reason: "INVALID_STATE", current: plan.status };
  }

  // Idempotency: collapse a double-click into a single approval.
  if (!claimIdempotencyKey(`plan:${planId}:approve:${user.staffId}`)) {
    return { ok: false, reason: "DUPLICATE" };
  }

  const now = new Date().toISOString();
  updatePlan(planId, {
    status: "Approved",
    approvedAt: now,
    approvedById: user.staffId,
  });

  emitAudit({
    action: "plan.approved",
    subjectKind: "Plan",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { previousStatus: "SubmittedForApproval" },
  });
  emitNotification({
    userId: plan.authorId,
    template: "plan.approved",
    channel: "Inbox",
    title: `Your ${plan.monthIso} plan was approved`,
    body: `${user.name} approved your plan. Weekly fund requests have been generated.`,
    href: `/plans/${planId}`,
  });

  // Fire W5 auto-generation. The generator returns a list of the new
  // requests; we attach the ids to the audit so the approver can
  // click through to verify in dev.
  const gen = await generateWeeklyFundRequestsForPlan(planId);
  if (gen.ok) {
    emitAudit({
      action: "plan.weeklyRequestsGenerated",
      subjectKind: "Plan",
      subjectId: planId,
      actorId: "SYSTEM",
      actorRole: "System",
      payload: { count: gen.requestIds.length, requestIds: gen.requestIds },
    });
  } else {
    emitAudit({
      action: "plan.weeklyRequestsGenerationFailed",
      subjectKind: "Plan",
      subjectId: planId,
      actorId: "SYSTEM",
      actorRole: "System",
      payload: { reason: gen.reason },
    });
  }

  revalidatePlanSurfaces(planId);
  return { ok: true, id: planId, generatedRequestIds: gen.ok ? gen.requestIds : undefined };
}

// ─── 7. returnPlan ──────────────────────────────────────────────────

export async function returnPlan(planId: string, reason: string): Promise<PlanActionResult> {
  const user = await getCurrentUser();
  if (!PLAN_REVIEWER_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (!reason || reason.trim().length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }
  const plan = findPlan(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (plan.status !== "SubmittedForApproval") {
    return { ok: false, reason: "INVALID_STATE", current: plan.status };
  }

  updatePlan(planId, { status: "Returned", returnedReason: reason.trim() });

  emitAudit({
    action: "plan.returned",
    subjectKind: "Plan",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { previousStatus: "SubmittedForApproval", reason: reason.trim() },
  });
  emitNotification({
    userId: plan.authorId,
    template: "plan.returned",
    channel: "Inbox",
    title: `Your ${plan.monthIso} plan was returned`,
    body: reason.trim(),
    href: `/plans/${planId}`,
  });

  revalidatePlanSurfaces(planId);
  return { ok: true, id: planId };
}

// ─── 8. activatePlan ────────────────────────────────────────────────
//
// Flips the plan to Active at the start of the month. Activities
// previously "Planned" become available for execution (i.e. they
// show on /today, /calendar). We don't auto-fire this on a cron in
// mock-mode — a deliberate call from the CPL or a scheduled job.

export async function activatePlan(planId: string): Promise<PlanActionResult> {
  const user = await getCurrentUser();
  if (!PLAN_REVIEWER_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const plan = findPlan(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (plan.status !== "Approved") {
    return { ok: false, reason: "INVALID_STATE", current: plan.status };
  }
  updatePlan(planId, { status: "Active" });

  emitAudit({
    action: "plan.activated",
    subjectKind: "Plan",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  emitNotificationFanOut([plan.authorId], {
    template: "plan.activated",
    channel: "Inbox",
    title: `${plan.monthIso} plan is now active`,
    body: "Your scheduled activities are open for execution.",
    href: `/plans/${planId}`,
  });

  revalidatePlanSurfaces(planId);
  return { ok: true, id: planId };
}

// ─── 9. closePlan ───────────────────────────────────────────────────
//
// End-of-month closure. The plan is frozen; activities still allow
// status updates (Completed/Verified) but new lines can't be added.
// Closure also blocks any further weekly fund request generation
// against this plan.

export async function closePlan(planId: string): Promise<PlanActionResult> {
  const user = await getCurrentUser();
  if (!PLAN_REVIEWER_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const plan = findPlan(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (plan.status !== "Active") {
    return { ok: false, reason: "INVALID_STATE", current: plan.status };
  }
  updatePlan(planId, { status: "Closed" });

  emitAudit({
    action: "plan.closed",
    subjectKind: "Plan",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });

  revalidatePlanSurfaces(planId);
  return { ok: true, id: planId };
}

// ─── Helpers ────────────────────────────────────────────────────────

function recomputePlanTotal(planId: string): number {
  const total = activitiesStore()
    .filter((a) => a.planId === planId && a.status !== "Cancelled")
    .reduce((sum, a) => sum + a.estCostCents, 0);
  updatePlan(planId, { totalCostCents: total });
  return total;
}

function revalidatePlanSurfaces(planId?: string) {
  try {
    revalidatePath("/plans");
    if (planId) revalidatePath(`/plans/${planId}`);
    revalidatePath("/my-plan");
    revalidatePath("/today");
    revalidatePath("/calendar");
    revalidatePath("/approvals");
    revalidatePath("/dashboards/cceo");
    revalidatePath("/dashboards/cpl");
    revalidatePath("/dashboards/director");
    revalidatePath("/notifications");
  } catch {
    /* outside request context */
  }
}
