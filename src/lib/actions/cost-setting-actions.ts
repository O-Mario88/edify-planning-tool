"use server";

// W4 — Cost & cost-settings server actions.
//
// State machine:
//   Draft → (submit) → Draft (awaiting CD review)
//                   → (approve) → Active
//                                ↳ previous Active row in the same
//                                  (countryId, activityKind, effectiveFyIso)
//                                  is auto-Superseded.
//
// Calling approve also fans out an inbox notification to every CCEO
// in the country: their plans need re-costing because the per-unit
// rate just changed. recomputePlanCosts() is the action they call
// (or that an automation runs nightly) to re-run cost-engine on a
// specific plan and update totalCostCents in lockstep.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";
import {
  type ActivityKind,
  type CostSettingRecord,
  type CostSettingStatus,
  activities as activitiesStore,
  costSettings as costSettingsStore,
  findCostSetting,
  findPlan,
  newId,
  plans as plansStore,
  updateCostSetting,
  updatePlan,
} from "./store";

// ─── Result types ───────────────────────────────────────────────────

export type CostSettingResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_STATE"; current: CostSettingStatus }
  | { ok: false; reason: "INVALID_INPUT"; field: string }
  | { ok: false; reason: "DUPLICATE_DRAFT" };

// ─── Authorisation ──────────────────────────────────────────────────
//
// • Propose / submit → Country Director and Program Accountant (the
//   two roles that know the country's cost reality).
// • Approve         → Country Director only (final sign-off).
// • Admin overrides both for support.

const COST_AUTHOR_ROLES = new Set(["CountryDirector", "ProgramAccountant", "Admin"]);
const COST_APPROVER_ROLES = new Set(["CountryDirector", "Admin"]);

// ─── 1. proposeCostSetting ─────────────────────────────────────────

export async function proposeCostSetting(
  activityKind: ActivityKind,
  effectiveFyIso: string,
  costPerUnitCents: number,
  countryId: string = "Uganda",
): Promise<CostSettingResult> {
  const user = await getCurrentUser();
  if (!COST_AUTHOR_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (!/^\d{4}-FY$/.test(effectiveFyIso)) {
    return { ok: false, reason: "INVALID_INPUT", field: "effectiveFyIso" };
  }
  if (!Number.isInteger(costPerUnitCents) || costPerUnitCents < 0) {
    return { ok: false, reason: "INVALID_INPUT", field: "costPerUnitCents" };
  }
  // Only one Draft per (country, kind, FY) — proposing again should
  // edit the existing draft, not create another.
  if (
    costSettingsStore().some(
      (c) =>
        c.countryId === countryId &&
        c.activityKind === activityKind &&
        c.effectiveFyIso === effectiveFyIso &&
        c.status === "Draft",
    )
  ) {
    return { ok: false, reason: "DUPLICATE_DRAFT" };
  }

  const now = new Date().toISOString();
  const setting: CostSettingRecord = {
    id: newId("cost"),
    countryId,
    activityKind,
    effectiveFyIso,
    costPerUnitCents,
    status: "Draft",
    proposedById: user.staffId,
    createdAt: now,
    updatedAt: now,
  };
  costSettingsStore().push(setting);

  emitAudit({
    action: "costSetting.proposed",
    subjectKind: "CostSetting",
    subjectId: setting.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { activityKind, effectiveFyIso, costPerUnitCents },
  });

  revalidateCostSurfaces();
  return { ok: true, id: setting.id };
}

// ─── 2. submitCostSettingForApproval ───────────────────────────────
//
// In the current model a "Draft" cost-setting is itself the in-review
// state — there's no separate "Submitted" enum. So this action emits
// the CD notification + audit, but does not change the stored status.
// (When a separate "PendingApproval" status is added to the schema,
// it'll go here without changing the API.)

export async function submitCostSettingForApproval(id: string): Promise<CostSettingResult> {
  const user = await getCurrentUser();
  const setting = findCostSetting(id);
  if (!setting) return { ok: false, reason: "NOT_FOUND" };
  if (!COST_AUTHOR_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (setting.status !== "Draft") {
    return { ok: false, reason: "INVALID_STATE", current: setting.status };
  }
  if (user.staffId !== setting.proposedById && user.role !== "Admin") {
    // Only the proposer (or Admin) can submit.
    return { ok: false, reason: "FORBIDDEN" };
  }

  emitAudit({
    action: "costSetting.submittedForApproval",
    subjectKind: "CostSetting",
    subjectId: id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  emitNotificationFanOut(["COUNTRY_DIRECTOR"], {
    template: "costSetting.submittedForApproval",
    channel: "Inbox",
    title: `New ${setting.activityKind} rate for ${setting.effectiveFyIso} needs sign-off`,
    body: `${user.name} proposed ${(setting.costPerUnitCents / 100).toLocaleString()} UGX per unit.`,
    href: `/cost-settings?id=${id}`,
  });

  revalidateCostSurfaces();
  return { ok: true, id };
}

// ─── 3. approveCostSetting ─────────────────────────────────────────
//
// Activates the new rate AND supersedes the previous Active row in
// the same (countryId, activityKind, effectiveFyIso). Notifies every
// CCEO so they know their plans need re-costing.

export async function approveCostSetting(id: string): Promise<CostSettingResult & { supersededId?: string }> {
  const user = await getCurrentUser();
  if (!COST_APPROVER_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const setting = findCostSetting(id);
  if (!setting) return { ok: false, reason: "NOT_FOUND" };
  if (setting.status !== "Draft") {
    return { ok: false, reason: "INVALID_STATE", current: setting.status };
  }

  // Find the currently-active sibling so it can be marked Superseded
  // in the SAME logical step. In Prisma-land this is one $transaction;
  // here we update both rows back-to-back.
  const sibling = costSettingsStore().find(
    (c) =>
      c.id !== id &&
      c.countryId === setting.countryId &&
      c.activityKind === setting.activityKind &&
      c.effectiveFyIso === setting.effectiveFyIso &&
      c.status === "Active",
  );

  const now = new Date().toISOString();
  if (sibling) {
    updateCostSetting(sibling.id, { status: "Superseded", supersededAt: now });
  }
  updateCostSetting(id, {
    status: "Active",
    approvedById: user.staffId,
    approvedAt: now,
  });

  emitAudit({
    action: "costSetting.approved",
    subjectKind: "CostSetting",
    subjectId: id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      activityKind: setting.activityKind,
      effectiveFyIso: setting.effectiveFyIso,
      costPerUnitCents: setting.costPerUnitCents,
      supersededId: sibling?.id,
    },
  });

  // Fan-out: every CCEO with a Draft/Returned plan in this country
  // should re-cost. In the mock we don't know who that is, so we
  // notify a synthetic "ALL_CCEO" channel; production resolves the
  // real recipient list from the staff directory.
  const affectedPlanAuthors = Array.from(
    new Set(plansStore().filter((p) => p.countryId === setting.countryId && (p.status === "Draft" || p.status === "Returned")).map((p) => p.authorId)),
  );
  if (affectedPlanAuthors.length > 0) {
    emitNotificationFanOut(affectedPlanAuthors, {
      template: "costSetting.activated",
      channel: "Inbox",
      title: `${setting.activityKind} cost rate updated`,
      body: `New rate: ${(setting.costPerUnitCents / 100).toLocaleString()} UGX per unit. Re-cost your draft plans before submitting.`,
      href: `/cost-settings?id=${id}`,
    });
  }

  revalidateCostSurfaces();
  return { ok: true, id, supersededId: sibling?.id };
}

// ─── 4. recomputePlanCosts ─────────────────────────────────────────
//
// Re-runs the cost calculation for every activity on a plan using
// the latest Active CostSetting per ActivityKind. Returns the new
// totalCostCents on success.
//
// Production note: a nightly cron should call this for every
// Draft/Returned plan after any approveCostSetting, so authors don't
// have to remember to re-cost manually.

export async function recomputePlanCosts(
  planId: string,
): Promise<CostSettingResult & { newTotalCostCents?: number }> {
  const user = await getCurrentUser();
  const plan = findPlan(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (!COST_AUTHOR_ROLES.has(user.role) && plan.authorId !== user.staffId) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (plan.status !== "Draft" && plan.status !== "Returned") {
    return { ok: false, reason: "INVALID_STATE", current: "Draft" as CostSettingStatus };
  }

  // Build a lookup of the active rate per ActivityKind in this country.
  const rateByKind = new Map<ActivityKind, number>();
  for (const cs of costSettingsStore()) {
    if (cs.status !== "Active") continue;
    if (cs.countryId !== plan.countryId) continue;
    rateByKind.set(cs.activityKind, cs.costPerUnitCents);
  }

  // Recompute each activity's estCostCents from the live rate. We
  // intentionally don't change the activity row's `estCostCents` field
  // if no Active rate exists — keeping the old number is safer than
  // zeroing it out and silently shrinking the plan total.
  const affected = activitiesStore().filter((a) => a.planId === planId);
  let touched = 0;
  for (const a of affected) {
    const rate = rateByKind.get(a.kind);
    if (rate == null) continue;
    if (a.estCostCents !== rate) {
      a.estCostCents = rate;
      a.updatedAt = new Date().toISOString();
      touched += 1;
    }
  }
  const newTotal = affected
    .filter((a) => a.status !== "Cancelled")
    .reduce((sum, a) => sum + a.estCostCents, 0);
  updatePlan(planId, { totalCostCents: newTotal });

  emitAudit({
    action: "plan.recosted",
    subjectKind: "Plan",
    subjectId: planId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { activitiesTouched: touched, newTotalCostCents: newTotal },
  });

  revalidateCostSurfaces();
  try { revalidatePath(`/plans/${planId}`); } catch {}
  return { ok: true, id: planId, newTotalCostCents: newTotal };
}

// ─── Helpers ────────────────────────────────────────────────────────

function revalidateCostSurfaces() {
  try {
    revalidatePath("/cost-settings");
    revalidatePath("/budget/breakdown");
    revalidatePath("/budget/scenarios");
    revalidatePath("/approvals");
    revalidatePath("/dashboards/director");
    revalidatePath("/dashboards/accountant");
    revalidatePath("/notifications");
  } catch {
    /* outside request context */
  }
}
