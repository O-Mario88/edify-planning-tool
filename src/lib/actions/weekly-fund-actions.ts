"use server";

// W5 — Weekly Fund Pipeline server actions.
//
// These are THIN wrappers around the pure-function engine in
// `src/lib/funds/weekly-fund-engine.ts`. Every action:
//
//   1. Resolves the actor and checks the role gate.
//   2. Reads the entity from the store.
//   3. Calls the engine function (which validates the state transition
//      and produces a new entity + audit + notification events).
//   4. If ok, persists the new entity, bridges the engine's audit /
//      notifications into the canonical sink, and revalidates the
//      surfaces that show this entity.
//   5. Returns a discriminated-union result the UI can switch on.
//
// Where the audit flagged gaps in the engine — double-disbursement,
// idempotency on accountability NetSuite ID, server-side eligibility
// gate, >15% accountant re-approval — those guards live here, in the
// action layer, before the engine call.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut, type AuditEventRecord } from "./audit";
import {
  type BalanceReturn,
  type DisbursementRecord,
  type FundsReceivedRecord,
  type Money,
  type ReimbursementClaim,
  type WeeklyFundRequest,
  type WeeklyFundRequestStatus,
  balanceReturns as balanceReturnsStore,
  claimIdempotencyKey,
  disbursementExistsFor,
  disbursements as disbursementsStore,
  findDisbursement,
  findFundRequest,
  findPlan,
  fundRequests as fundRequestsStore,
  fundsReceived as fundsReceivedStore,
  newId,
  reimbursements as reimbursementsStore,
  updateDisbursement,
  upsertFundRequest,
} from "./store";
import {
  approveReimbursementBySupervisor,
  approveWeeklyFundAccountability,
  approveWeeklyFundRequestByLead,
  calculateWeeklyFundRequestTotal,
  checkWeeklyFundRequestEligibility,
  confirmBalanceReturn as confirmBalanceReturnEngine,
  confirmFundsReceived,
  confirmStaffReceipt,
  confirmWeeklyFundRequest,
  disburseWeeklyFundRequest,
  generateWeeklyFundRequestsFromApprovedPlan,
  OVERSPEND_HIGH_THRESHOLD_PCT,
  priorWeekClosedFor,
  reconcileAccountability,
  reimburseClaim,
  resolveReimbursementRoute,
  returnWeeklyFundRequestByLead,
  submitReimbursementClaim,
  submitWeeklyFundAccountability,
  ZERO_UGX,
} from "@/lib/funds/weekly-fund-engine";
import type {
  BalanceReturnMethod,
  DisbursementMethod,
  FundAccountability,
  WeeklyFundAuditEvent,
  WeeklyFundNotification,
} from "@/lib/funds/weekly-fund-types";
import { activities as activitiesStore } from "./store";
import { isValidId } from "@/lib/intake/id-formats";
import {
  activeCostFor,
  type CostItem,
} from "@/lib/cost-settings-mock";
import type { ActivityKind } from "@/lib/actions/store";

// Activity kind → cost-catalogue item. Drives plan-derived weekly
// fund generation so changing a catalogue rate at /cost-settings
// flows into next week's slip without code changes (audit-flagged
// gap — generation previously hardcoded a.estCostCents only).
const KIND_TO_CATALOGUE: Record<ActivityKind, CostItem> = {
  CLUSTER_TRAINING:   "Cluster training cost",
  IN_SCHOOL_COACHING: "In-School coaching cost",
  SCHOOL_VISIT:       "Staff school visit cost",
  SSA_FOLLOW_UP:      "SSA support cost",
  HANDOVER_MEETING:   "Cluster Meeting Cost Per Participant",
  LESSON_OBSERVATION: "Staff school visit cost",
  PARTNER_FOLLOW_UP:  "Partner school visit cost",
  TRAINING_FOLLOW_UP: "Training Session Fee",
  DATA_COLLECTION:    "SSA verification cost",
  COURTESY_VISIT:     "Staff school visit cost",
};

/** Look up the CD-approved catalogue unit cost for an activity kind;
 *  returns null when no Active rate exists so the caller can fall
 *  back to the activity's own estimate. */
function catalogueUnitCostFor(kind: ActivityKind): number | null {
  const item = KIND_TO_CATALOGUE[kind];
  if (!item) return null;
  const rate = activeCostFor(item);
  return rate > 0 ? rate : null;
}

// ─── Result types ──────────────────────────────────────────────────

export type FundActionResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_STATE"; current: WeeklyFundRequestStatus | string }
  | { ok: false; reason: "INVALID_INPUT"; field: string }
  | { ok: false; reason: "BLOCKED"; blockers: string[] }
  | { ok: false; reason: "DUPLICATE" }
  | { ok: false; reason: "ENGINE_ERROR"; error: string };

// ─── Role gates ────────────────────────────────────────────────────

const STAFF_ROLES   = new Set(["CCEO", "Admin"]);
const LEAD_ROLES    = new Set(["CountryProgramLead", "CountryDirector", "Admin"]);
const ACCT_ROLES    = new Set(["ProgramAccountant", "Admin"]);
const IA_ROLES      = new Set(["ImpactAssessment", "Admin"]);

// Approver-correctness: a CCEO weekly request is approved by its Program
// Lead; every other requester (PL / IA / Accountant / SP) goes to the
// Country Director. Without this, LEAD_ROLES let a CD approve/return an
// individual CCEO weekly request — the CCEO+PL chain the spec reserves
// for the PL. Admin always passes.
function isCorrectApprover(userRole: string, req: { requesterRole?: string; staffRole?: string }): boolean {
  if (userRole === "Admin") return true;
  const requester = req.requesterRole ?? req.staffRole ?? "CCEO";
  const requiredApproverRole = requester === "CCEO" ? "CountryProgramLead" : "CountryDirector";
  return userRole === requiredApproverRole;
}
const CD_ROLES      = new Set(["CountryDirector", "Admin"]);

function actorIdOf(user: { staffId: string; name: string }) {
  return { id: user.staffId, name: user.name };
}

// ─── Audit / notification bridge ───────────────────────────────────
//
// The engine emits its own typed events. Bridge them into the
// canonical sink so /admin/audit-log + /notifications can read the
// full history regardless of which workflow produced it.

function bridgeAudit(events: WeeklyFundAuditEvent[], actorRole: string): void {
  for (const e of events) {
    emitAudit({
      action: `weeklyFund.${e.action.toLowerCase()}`,
      subjectKind: "WeeklyFundRequest",
      subjectId: e.weeklyFundRequestId,
      actorId: e.actorId,
      actorRole: actorRole || e.actorRole,
      actorName: e.actorName,
      payload: {
        previousStatus: e.fromStatus,
        newStatus: e.toStatus,
        note: e.note,
        delta: e.delta,
      },
    } satisfies Omit<AuditEventRecord, "id" | "createdAt">);
  }
}

function bridgeNotifications(events: WeeklyFundNotification[]): void {
  // Group by recipient role; in mock-mode the userId is often a
  // role-token (e.g. "ACCOUNTANT"). Production resolves the staff
  // directory to a real id list.
  for (const n of events) {
    emitNotificationFanOut([n.audienceUserId], {
      template: `weeklyFund.${n.template.toLowerCase()}`,
      channel: n.channel,
      title: titleForTemplate(n.template, n.weeklyFundRequestId),
      body: `Request ${n.weeklyFundRequestId}.`,
      href: `/fund-requests/${n.weeklyFundRequestId}`,
    });
  }
}

function titleForTemplate(template: string, reqId: string): string {
  // Light human-friendly mapping; the production copy + i18n catalog
  // lives in the backend Notification template registry.
  switch (template) {
    case "REQUEST_AUTO_GENERATED":  return "Weekly fund request ready to submit";
    case "REQUEST_SUBMITTED":       return "Fund request awaiting your approval";
    case "REQUEST_APPROVED":        return "Fund request approved";
    case "REQUEST_RETURNED":        return "Fund request returned";
    case "REQUEST_DISBURSED":       return "Funds disbursed";
    case "RECEIPT_REMINDER":        return "Confirm fund receipt";
    case "ACCOUNTABILITY_DUE":      return "Accountability ready to review";
    case "ACCOUNTABILITY_APPROVED": return "Accountability approved · week closed";
    default:                        return `Update on ${reqId}`;
  }
}

// ─── Revalidation fan-out ──────────────────────────────────────────

function revalidateFundSurfaces(reqId?: string) {
  try {
    revalidatePath("/fund-requests");
    if (reqId) revalidatePath(`/fund-requests/${reqId}`);
    revalidatePath("/weekly-funds");
    revalidatePath("/approvals");
    revalidatePath("/disbursements");
    revalidatePath("/dashboards/accountant");
    revalidatePath("/dashboards/cpl");
    revalidatePath("/dashboards/director");
    revalidatePath("/dashboards/rvp");
    revalidatePath("/notifications");
  } catch { /* outside request context */ }
}

// ═══════════════════════════════════════════════════════════════════
// 1. generateWeeklyFundRequestsForPlan
// ───────────────────────────────────────────────────────────────────
// Called by plan-actions.approvePlan immediately after the plan flips
// to Approved. Returns the ids of the new requests so the approver
// can see how many split out.

export async function generateWeeklyFundRequestsForPlan(
  planId: string,
): Promise<{ ok: true; requestIds: string[] } | { ok: false; reason: string }> {
  // Auth: this is an exported "use server" action (callable by any
  // session), and it mints + upserts money records. Only the staff who
  // owns the plan, their lead, or Admin may trigger generation. Other
  // server actions call it internally AFTER their own role gate, so the
  // re-check here is cheap and closes the public-endpoint hole.
  const user = await getCurrentUser();
  if (!STAFF_ROLES.has(user.role) && !LEAD_ROLES.has(user.role)) {
    return { ok: false, reason: "Forbidden" };
  }
  const plan = findPlan(planId);
  if (!plan) return { ok: false, reason: "Plan not found" };

  // The engine groups by (staffId × weekOfMonth). For mock-mode we
  // pass a single staff (the plan author) with their activities split
  // by weekOfMonth. Real backend will resolve assignees per activity.
  const allActivities = activitiesStore().filter((a) => a.planId === planId);
  if (allActivities.length === 0) return { ok: false, reason: "Plan has no activities" };

  const planActivityInputs = allActivities.map((a) => {
    // Prefer the CD-approved catalogue rate so a rate change at
    // /cost-settings carries straight into the next slip. Fall back
    // to the activity's own estimate when the catalogue is missing.
    const rate = catalogueUnitCostFor(a.kind);
    const unit = rate ?? a.estCostCents;
    return ({
      id: a.id,
      staffId: a.assigneeId ?? plan.authorId,
      staffName: plan.authorName,
      staffRole: "CCEO" as const,
      district: "Northern District", // mock — production reads from User.district
      programLeadId: "PL_DEFAULT",
      programLeadName: "Program Lead",
      countryId: plan.countryId,
      monthlyPlanId: planId,
      weekOfMonth: Math.min(Math.max(a.weekOfMonth, 1), 4) as 1 | 2 | 3 | 4,
      activity: {
        id: a.id,
        originPlanLineId: a.id,
        kind: "SchoolVisit" as const,
        title: a.title,
        plannedDay: a.scheduledDate ?? "Mon",
        costBreakdown: {
          transport: { amount: unit, currency: "UGX" as const },
          allowance: ZERO_UGX,
          meals:     ZERO_UGX,
          materials: ZERO_UGX,
          misc:      ZERO_UGX,
        },
        totalCost: { amount: unit, currency: "UGX" as const },
        status: "Planned" as const,
      },
    });
  });

  const period = {
    fyLabel: "FY 2026",
    quarter: "Q4" as const,
    monthLabel: plan.monthIso,
    monthIso: plan.monthIso,
  };
  // Mock week ranges — production computes from the monthIso.
  const weekRanges = {
    1: { startIso: `${plan.monthIso}-06`, endIso: `${plan.monthIso}-12` },
    2: { startIso: `${plan.monthIso}-13`, endIso: `${plan.monthIso}-19` },
    3: { startIso: `${plan.monthIso}-20`, endIso: `${plan.monthIso}-26` },
    4: { startIso: `${plan.monthIso}-27`, endIso: `${plan.monthIso}-30` },
  } as const;

  const result = generateWeeklyFundRequestsFromApprovedPlan(
    planActivityInputs,
    period,
    weekRanges,
  );
  if (!result.ok || !result.data) {
    return { ok: false, reason: result.error ?? "Engine refused split" };
  }

  for (const req of result.data) upsertFundRequest(req);
  bridgeAudit(result.audit, "System");
  bridgeNotifications(result.notifications);
  revalidateFundSurfaces();

  return { ok: true, requestIds: result.data.map((r) => r.id) };
}

// ═══════════════════════════════════════════════════════════════════
// 2. editFundRequest (AUTO_GENERATED → DRAFT)
// ───────────────────────────────────────────────────────────────────
// Opens the request for staff edits. Staff is the only caller; the
// engine treats this as an implicit "I'm working on this" handshake.

export async function editFundRequest(reqId: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!STAFF_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (req.staffId !== user.staffId && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (req.status !== "AUTO_GENERATED") {
    return { ok: false, reason: "INVALID_STATE", current: req.status };
  }
  upsertFundRequest({ ...req, status: "DRAFT" });
  emitAudit({
    action: "weeklyFund.opened",
    subjectKind: "WeeklyFundRequest",
    subjectId: reqId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { previousStatus: "AUTO_GENERATED", newStatus: "DRAFT" },
  });
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 3. submitFundRequest (DRAFT → SUBMITTED)
// ═══════════════════════════════════════════════════════════════════

export async function submitFundRequest(reqId: string, note?: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!STAFF_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (req.staffId !== user.staffId && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const res = confirmWeeklyFundRequest(req, actorIdOf(user), { note });
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "submit failed" };
  upsertFundRequest(res.data);
  bridgeAudit(res.audit, user.role);
  bridgeNotifications(res.notifications);
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 4. approveFundRequest (SUBMITTED → APPROVED)
// ═══════════════════════════════════════════════════════════════════

export async function approveFundRequest(reqId: string, note?: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!LEAD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  // Idempotency: collapse double-clicks into a single approval.
  if (!claimIdempotencyKey(`weeklyFund:${reqId}:approve:${user.staffId}`)) {
    return { ok: false, reason: "DUPLICATE" };
  }
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (!isCorrectApprover(user.role, req)) return { ok: false, reason: "FORBIDDEN" };
  const res = approveWeeklyFundRequestByLead(req, actorIdOf(user), { note });
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "approve failed" };
  upsertFundRequest(res.data);
  bridgeAudit(res.audit, user.role);
  bridgeNotifications(res.notifications);
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 4b. verifyFundRequestByIa (sets iaVerifiedAt → unblocks disburse)
// ───────────────────────────────────────────────────────────────────
// IA gate (B12). CCEO weekly fund requests must clear Impact Assessment
// before the Accountant disburses. IA reviews the underlying activity
// plan + prior accountability and stamps `iaVerifiedAt`; the disburse
// action then proceeds. PL/IA/Accountant/Admin requests skip this gate.

export async function verifyFundRequestByIa(reqId: string, note?: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!IA_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!claimIdempotencyKey(`weeklyFund:${reqId}:iaVerify:${user.staffId}`)) {
    return { ok: false, reason: "DUPLICATE" };
  }
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (req.status !== "APPROVED" && req.status !== "READY_TO_DISBURSE") {
    return { ok: false, reason: "INVALID_STATE", current: req.status };
  }
  if (req.iaVerifiedAt) return { ok: true, id: reqId };

  upsertFundRequest({
    ...req,
    iaVerifiedAt: new Date().toISOString(),
    iaVerifiedById: user.staffId,
  });
  emitAudit({
    action: "weeklyFund.iaVerified",
    subjectKind: "WeeklyFundRequest",
    subjectId: reqId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { note },
  });
  emitNotificationFanOut(["ACCOUNTANT"], {
    template: "weeklyFund.iaVerified",
    channel: "Inbox",
    title: `Fund request ${reqId} cleared by IA`,
    body: "Impact Assessment verified the underlying plan. Disbursement unblocked.",
    href: "/disbursements",
  });
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 5. returnFundRequest (SUBMITTED → RETURNED_TO_STAFF)
// ═══════════════════════════════════════════════════════════════════

export async function returnFundRequest(reqId: string, reason: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!LEAD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!reason || reason.trim().length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (!isCorrectApprover(user.role, req)) return { ok: false, reason: "FORBIDDEN" };
  const res = returnWeeklyFundRequestByLead(req, actorIdOf(user), reason);
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "return failed" };
  upsertFundRequest(res.data);
  bridgeAudit(res.audit, user.role);
  bridgeNotifications(res.notifications);
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 6. markReadyToDisburse (APPROVED → READY_TO_DISBURSE)
// ───────────────────────────────────────────────────────────────────
// SERVER-SIDE ELIGIBILITY GATE — addresses the audit-flagged bug where
// the UI showed blockers but the backend didn't enforce them.

export async function markReadyToDisburse(
  reqId: string,
  fundsReceivedId: string,
): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!ACCT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (req.status !== "APPROVED" && req.status !== "HOLD_NO_FUNDS_AVAILABLE" && req.status !== "BLOCKED_PRIOR_OUTSTANDING") {
    return { ok: false, reason: "INVALID_STATE", current: req.status };
  }
  const batch = fundsReceivedStore().find((b) => b.id === fundsReceivedId);
  if (!batch) return { ok: false, reason: "NOT_FOUND" };

  // Build the eligibility context from live store state. The blockers
  // returned by the engine are the same ones the UI shows.
  const blockers = checkWeeklyFundRequestEligibility(req, {
    priorWeekClosed: priorWeekClosedFor(req, fundRequestsStore()),
    fundsAvailableAtCountry: batch.availableBalance,
    planActivityIds: new Set(req.activities.map((a) => a.originPlanLineId)),
    costTolerancePct: 10,
  });
  if (blockers.length > 0) {
    return { ok: false, reason: "BLOCKED", blockers };
  }

  upsertFundRequest({ ...req, status: "READY_TO_DISBURSE" });
  emitAudit({
    action: "weeklyFund.readyToDisburse",
    subjectKind: "WeeklyFundRequest",
    subjectId: reqId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { fundsReceivedId },
  });
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 7. recordFundsReceived (Accountant inflow)
// ═══════════════════════════════════════════════════════════════════

export type FundsReceivedInput = {
  countryId: string;
  receivedOnIso: string;
  fromSource: "RVP_OFFICE" | "HQ_TREASURY" | "PARTNER";
  reference: string;
  totalReceived: Money;
  monthLabel: string;
  notes?: string;
};

export async function recordFundsReceived(input: FundsReceivedInput): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!ACCT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!input.reference || input.reference.trim().length < 3) {
    return { ok: false, reason: "INVALID_INPUT", field: "reference" };
  }
  if (input.totalReceived.amount <= 0) {
    return { ok: false, reason: "INVALID_INPUT", field: "totalReceived" };
  }
  // Idempotency on (countryId, reference) — same bank transfer reference
  // cannot be booked twice.
  if (!claimIdempotencyKey(`fundsReceived:${input.countryId}:${input.reference}`)) {
    return { ok: false, reason: "DUPLICATE" };
  }

  const res = confirmFundsReceived({
    ...input,
    confirmedByAccountantId: user.staffId,
    accountant: actorIdOf(user),
  });
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "record failed" };
  fundsReceivedStore().push(res.data);
  emitAudit({
    action: "fundsReceived.recorded",
    subjectKind: "FundsReceived",
    subjectId: res.data.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { reference: input.reference, totalReceived: input.totalReceived.amount },
  });
  revalidateFundSurfaces();
  return { ok: true, id: res.data.id };
}

// ═══════════════════════════════════════════════════════════════════
// 8. disburseFundRequest (READY_TO_DISBURSE → DISBURSED)
// ───────────────────────────────────────────────────────────────────
// Enforces the unique-constraint guard (audit risk #2): one (request,
// fundsReceived) pair can produce at most one Disbursement row. A
// second click is rejected as DUPLICATE.

export type DisburseInput = {
  reqId: string;
  fundsReceivedId: string;
  method: DisbursementMethod;
  reference: string;
  amount: Money;
  note?: string;
};

export async function disburseFundRequest(input: DisburseInput): Promise<FundActionResult & { disbursementId?: string }> {
  const user = await getCurrentUser();
  if (!ACCT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  // Unique-constraint guard.
  if (disbursementExistsFor(input.reqId, input.fundsReceivedId)) {
    return { ok: false, reason: "DUPLICATE" };
  }

  const req = findFundRequest(input.reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  const batch = fundsReceivedStore().find((b) => b.id === input.fundsReceivedId);
  if (!batch) return { ok: false, reason: "NOT_FOUND" };
  if (!input.reference || input.reference.trim().length < 3) {
    return { ok: false, reason: "INVALID_INPUT", field: "reference" };
  }

  // IA verification gate (B12) — CCEO weekly fund requests cannot be
  // disbursed until Impact Assessment confirms the underlying activity
  // plan. PL/IA/Accountant/Admin requesters skip this gate.
  const requesterRole = req.requesterRole ?? req.staffRole;
  if (requesterRole === "CCEO" && !req.iaVerifiedAt) {
    return { ok: false, reason: "INVALID_STATE", current: "IA_VERIFICATION_REQUIRED" };
  }

  const res = disburseWeeklyFundRequest(req, {
    amount: input.amount,
    method: input.method,
    reference: input.reference.trim(),
    fundsReceivedId: input.fundsReceivedId,
    fundsAvailable: batch.availableBalance,
    accountant: actorIdOf(user),
    note: input.note,
    priorWeekClosed: priorWeekClosedFor(req, fundRequestsStore()),
  });
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "disburse failed" };

  upsertFundRequest(res.data.request);
  disbursementsStore().push(res.data.disbursement);
  // Reduce the batch's available balance in lockstep — without this,
  // a subsequent disbursement could over-draw.
  const idx = fundsReceivedStore().findIndex((b) => b.id === batch.id);
  if (idx !== -1) {
    const remaining = batch.availableBalance.amount - input.amount.amount;
    fundsReceivedStore()[idx] = {
      ...batch,
      availableBalance: { ...batch.availableBalance, amount: Math.max(remaining, 0) },
      totalAllocated: { ...batch.totalAllocated, amount: batch.totalAllocated.amount + input.amount.amount },
    };
  }
  bridgeAudit(res.audit, user.role);
  bridgeNotifications(res.notifications);
  revalidateFundSurfaces(input.reqId);
  return { ok: true, id: input.reqId, disbursementId: res.data.disbursement.id };
}

// ═══════════════════════════════════════════════════════════════════
// 9. confirmReceipt (DISBURSED → RECEIVED | dispute)
// ═══════════════════════════════════════════════════════════════════

export async function confirmReceipt(
  reqId: string,
  confirmed: boolean,
  disputeReason?: string,
): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!STAFF_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (req.staffId !== user.staffId && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }

  // Find the latest disbursement for this request.
  const dsbs = disbursementsStore().filter((d) => d.weeklyFundRequestId === reqId);
  const dsb = dsbs[dsbs.length - 1];
  if (!dsb) return { ok: false, reason: "NOT_FOUND" };

  if (!confirmed) {
    if (!disputeReason || disputeReason.trim().length < 5) {
      return { ok: false, reason: "INVALID_INPUT", field: "disputeReason" };
    }
    updateDisbursement(dsb.id, { receiptNote: `DISPUTED: ${disputeReason.trim()}` });
    emitAudit({
      action: "weeklyFund.receiptDisputed",
      subjectKind: "WeeklyFundRequest",
      subjectId: reqId,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: { disbursementId: dsb.id, reason: disputeReason.trim() },
    });
    revalidateFundSurfaces(reqId);
    return { ok: true, id: reqId };
  }

  const res = confirmStaffReceipt(req, dsb, actorIdOf(user));
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "confirm failed" };
  upsertFundRequest(res.data.request);
  updateDisbursement(dsb.id, res.data.disbursement);
  bridgeAudit(res.audit, user.role);
  bridgeNotifications(res.notifications);
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 10. markInUse (RECEIVED → IN_USE)
// ───────────────────────────────────────────────────────────────────
// In production this fires automatically on the first activity-
// completion under the week. Exposing as a manual server action gives
// the UI a way to drive the state machine in mock-mode + lets the
// nightly cron call it without weaving through the activity engine.

export async function markInUse(reqId: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  // Staff (own request) or any system actor (cron service-account).
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (!STAFF_ROLES.has(user.role) && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (req.status !== "RECEIVED") {
    return { ok: false, reason: "INVALID_STATE", current: req.status };
  }
  upsertFundRequest({ ...req, status: "IN_USE" });
  emitAudit({
    action: "weeklyFund.inUse",
    subjectKind: "WeeklyFundRequest",
    subjectId: reqId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 11. submitAccountability (IN_USE → ACCOUNTABILITY_SUBMITTED)
// ───────────────────────────────────────────────────────────────────
// IDEMPOTENCY ON NETSUITE ID — the audit-flagged risk #3. Re-submitting
// the same expense ID returns DUPLICATE rather than spawning duplicate
// downstream side effects (BalanceReturn, Reimbursement).

export type AccountabilityInput = {
  reqId: string;
  netsuiteId: string;
  amountSpentCents: number;
  amountReturnedCents?: number;
  receipts: { activityId: string; receiptRef: string; amountCents: number }[];
  notes?: string;
};

export async function submitAccountability(input: AccountabilityInput): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!STAFF_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const req = findFundRequest(input.reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (req.staffId !== user.staffId && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (!isValidId("expense", input.netsuiteId)) {
    return { ok: false, reason: "INVALID_INPUT", field: "netsuiteId" };
  }
  // Idempotency on (request, netsuiteId).
  if (!claimIdempotencyKey(`accountability:${input.reqId}:${input.netsuiteId.trim()}`)) {
    return { ok: false, reason: "DUPLICATE" };
  }
  const submission = {
    accountedAmount: { amount: input.amountSpentCents, currency: "UGX" as const },
    returnedAmount: { amount: input.amountReturnedCents ?? 0, currency: "UGX" as const },
    receipts: input.receipts.map((r) => ({
      activityId: r.activityId,
      receiptRef: r.receiptRef,
      amount: { amount: r.amountCents, currency: "UGX" as const },
    })),
    note: input.notes,
  };
  const res = submitWeeklyFundAccountability(req, actorIdOf(user), submission);
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "submit failed" };
  upsertFundRequest(res.data);
  bridgeAudit(res.audit, user.role);
  bridgeNotifications(res.notifications);
  revalidateFundSurfaces(input.reqId);
  return { ok: true, id: input.reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 12. approveAccountability (ACCOUNTABILITY_SUBMITTED → CLOSED)
// ═══════════════════════════════════════════════════════════════════

export async function approveAccountability(reqId: string, note?: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!LEAD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  const res = approveWeeklyFundAccountability(req, actorIdOf(user), { note });
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "approve failed" };
  upsertFundRequest(res.data);
  bridgeAudit(res.audit, user.role);
  bridgeNotifications(res.notifications);
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 13. returnAccountability (ACCOUNTABILITY_SUBMITTED → ACCOUNTABILITY_RETURNED)
// ═══════════════════════════════════════════════════════════════════

export async function returnAccountability(reqId: string, reason: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!LEAD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!reason || reason.trim().length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (req.status !== "ACCOUNTABILITY_SUBMITTED") {
    return { ok: false, reason: "INVALID_STATE", current: req.status };
  }
  upsertFundRequest({ ...req, status: "ACCOUNTABILITY_RETURNED" });
  emitAudit({
    action: "weeklyFund.accountabilityReturned",
    subjectKind: "WeeklyFundRequest",
    subjectId: reqId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { reason: reason.trim() },
  });
  emitNotificationFanOut([req.staffId], {
    template: "weeklyFund.accountabilityReturned",
    channel: "Inbox",
    title: "Accountability returned — please correct",
    body: reason.trim(),
    href: `/fund-requests/${reqId}`,
  });
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}

// ═══════════════════════════════════════════════════════════════════
// 14. createReimbursementClaim — auto from reconciliation OR manual
// ───────────────────────────────────────────────────────────────────
// The >15% overspend gate is computed inside the engine via
// `computeOverspendThreshold` — claims above the threshold are routed
// to CountryDirector, and the audit-flagged risk #5 (missing
// accountant re-approval) is enforced by `markReimbursed` requiring
// status === Queued for Accountant.

export type ManualReimbursementInput = {
  staffId: string;
  staffName: string;
  staffRole: ReimbursementClaim["staffRole"];
  activityId?: string;
  activityTitle?: string;
  weeklyPlanId?: string;
  fundRequestId?: string;
  amountSpentCents: number;
  amountPreviouslyDisbursedCents: number;
  reasonPersonalFundsUsed: string;
  netsuiteExpenseId: string;
  evidenceLinks?: string[];
};

export async function createReimbursementClaim(input: ManualReimbursementInput): Promise<FundActionResult> {
  const user = await getCurrentUser();
  // Staff submits their own claim; Admin can submit on behalf.
  if (user.staffId !== input.staffId && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  // Idempotency on (staff, netsuiteId).
  if (!claimIdempotencyKey(`reimburse:${input.staffId}:${input.netsuiteExpenseId}`)) {
    return { ok: false, reason: "DUPLICATE" };
  }
  const res = submitReimbursementClaim({
    staffId: input.staffId,
    staffName: input.staffName,
    staffRole: input.staffRole,
    activityId: input.activityId,
    activityTitle: input.activityTitle,
    weeklyPlanId: input.weeklyPlanId,
    fundRequestId: input.fundRequestId,
    amountSpentUgx: input.amountSpentCents,
    amountPreviouslyDisbursedUgx: input.amountPreviouslyDisbursedCents,
    reasonPersonalFundsUsed: input.reasonPersonalFundsUsed,
    netsuiteExpenseId: input.netsuiteExpenseId,
    evidenceLinks: input.evidenceLinks,
  });
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "submit failed" };
  reimbursementsStore().push(res.data);

  emitAudit({
    action: "reimbursement.submitted",
    subjectKind: "Reimbursement",
    subjectId: res.data.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      amountToReimburseUgx: res.data.amountToReimburseUgx,
      thresholdFlag: res.data.thresholdFlag,
      route: res.data.approvalRoute,
    },
  });
  // Notify the approval route. CCEO overspend > 15 % routes to CD,
  // otherwise to PL; non-CCEO always to CD.
  emitNotificationFanOut(
    [res.data.approvalRoute === "ProgramLead" ? "PROGRAM_LEAD" : "COUNTRY_DIRECTOR"],
    {
      template: "reimbursement.review",
      channel: "Inbox",
      title: `${input.staffName} submitted a reimbursement claim`,
      body: `Amount: ${(res.data.amountToReimburseUgx / 100).toLocaleString()} UGX · NetSuite ${res.data.netsuiteExpenseId}`,
      href: `/fund-requests/${input.fundRequestId ?? ""}`,
    },
  );
  revalidateFundSurfaces(input.fundRequestId);
  return { ok: true, id: res.data.id };
}

// ═══════════════════════════════════════════════════════════════════
// 15. approveReimbursement — PL → Accountant (four-eyes path)
// ═══════════════════════════════════════════════════════════════════

export async function approveReimbursement(claimId: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  // PL approves CCEO claims; CD approves non-CCEO and >15% CCEO claims.
  if (!LEAD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const claim = reimbursementsStore().find((c) => c.id === claimId);
  if (!claim) return { ok: false, reason: "NOT_FOUND" };

  // Enforce route gate: only the routed approver can advance the claim.
  if (claim.approvalRoute === "ProgramLead" && user.role !== "CountryProgramLead" && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (claim.approvalRoute === "CountryDirector" && !CD_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }

  const res = approveReimbursementBySupervisor(claim, actorIdOf(user));
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "approve failed" };
  const idx = reimbursementsStore().findIndex((c) => c.id === claimId);
  reimbursementsStore()[idx] = res.data;

  emitAudit({
    action: "reimbursement.supervisorApproved",
    subjectKind: "Reimbursement",
    subjectId: claimId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { thresholdFlag: claim.thresholdFlag },
  });
  emitNotificationFanOut(["ACCOUNTANT"], {
    template: "reimbursement.queuedForAccountant",
    channel: "Inbox",
    title: `Reimbursement ready for payout`,
    body: `${claim.staffName} · ${(claim.amountToReimburseUgx / 100).toLocaleString()} UGX`,
    href: `/dashboards/accountant`,
  });
  revalidateFundSurfaces();
  return { ok: true, id: claimId };
}

// ═══════════════════════════════════════════════════════════════════
// 16. markReimbursed — Accountant releases payment (four-eyes close)
// ───────────────────────────────────────────────────────────────────
// AUDIT FIX #5: re-approval gate. CCEO overspends > 15 % can only be
// reimbursed once both the CountryDirector AND the Accountant have
// signed (CD via approveReimbursement, Accountant here). The engine
// already enforces the precondition `status === Queued for Accountant`
// — we add the explicit threshold check so the route is unambiguous.

export async function markReimbursed(claimId: string, txRef: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (!ACCT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const claim = reimbursementsStore().find((c) => c.id === claimId);
  if (!claim) return { ok: false, reason: "NOT_FOUND" };
  if (!txRef || txRef.trim().length < 4) {
    return { ok: false, reason: "INVALID_INPUT", field: "txRef" };
  }
  // Four-eyes: high overspend must have been pre-approved by CD.
  if (claim.thresholdFlag === "RequiresCDReview" && claim.approvalRoute !== "CountryDirector") {
    return {
      ok: false,
      reason: "INVALID_STATE",
      current: `${claim.status} (high-overspend requires CD route)`,
    };
  }
  const res = reimburseClaim(claim, actorIdOf(user), txRef.trim());
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "pay failed" };
  const idx = reimbursementsStore().findIndex((c) => c.id === claimId);
  reimbursementsStore()[idx] = res.data;

  emitAudit({
    action: "reimbursement.paid",
    subjectKind: "Reimbursement",
    subjectId: claimId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { transactionReference: txRef.trim(), amount: claim.amountToReimburseUgx },
  });
  emitNotificationFanOut([claim.staffId], {
    template: "reimbursement.paid",
    channel: "Inbox",
    title: "Reimbursement paid",
    body: `${(claim.amountToReimburseUgx / 100).toLocaleString()} UGX · ref ${txRef.trim()}`,
  });
  revalidateFundSurfaces();
  return { ok: true, id: claimId };
}

// ═══════════════════════════════════════════════════════════════════
// 17. confirmBalanceReturn — Accountant confirms unspent funds returned
// ═══════════════════════════════════════════════════════════════════

export async function confirmBalanceReturn(
  returnId: string,
  method: BalanceReturnMethod,
  reference?: string,
): Promise<FundActionResult> {
  const user = await getCurrentUser();
  const balanceReturn = balanceReturnsStore().find((b) => b.id === returnId);
  if (!balanceReturn) return { ok: false, reason: "NOT_FOUND" };
  // Only the originating staff (or Admin) can declare the return method.
  // Engine also enforces this; we keep the role gate here so a CPL
  // can't accidentally close someone else's return.
  if (balanceReturn.staffId !== user.staffId && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const res = confirmBalanceReturnEngine(balanceReturn, actorIdOf(user), method, reference);
  if (!res.ok || !res.data) return { ok: false, reason: "ENGINE_ERROR", error: res.error ?? "confirm failed" };
  const idx = balanceReturnsStore().findIndex((b) => b.id === returnId);
  balanceReturnsStore()[idx] = res.data;

  emitAudit({
    action: "balanceReturn.confirmed",
    subjectKind: "BalanceReturn",
    subjectId: returnId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { method, reference, amount: balanceReturn.amountUgx },
  });
  emitNotificationFanOut(["ACCOUNTANT"], {
    template: "balanceReturn.confirmed",
    channel: "Inbox",
    title: `Balance return confirmed`,
    body: `${balanceReturn.staffName} · ${(balanceReturn.amountUgx / 100).toLocaleString()} UGX via ${method}`,
  });
  revalidateFundSurfaces();
  return { ok: true, id: returnId };
}

// ═══════════════════════════════════════════════════════════════════
// 18. closeFundRequest — explicit terminal close
// ───────────────────────────────────────────────────────────────────
// `approveAccountability` already closes the request as a side effect
// (engine emits both ACCOUNTABILITY_APPROVED and CLOSED in one step).
// This action exists for the rare manual closure path — e.g. an
// admin force-close after a stuck accountability return. Always
// audited as a manual override.

export async function closeFundRequest(reqId: string, reason: string): Promise<FundActionResult> {
  const user = await getCurrentUser();
  if (user.role !== "Admin") return { ok: false, reason: "FORBIDDEN" };
  if (!reason || reason.trim().length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }
  const req = findFundRequest(reqId);
  if (!req) return { ok: false, reason: "NOT_FOUND" };
  if (req.status === "CLOSED" || req.status === "ARCHIVED") {
    return { ok: false, reason: "INVALID_STATE", current: req.status };
  }
  const now = new Date().toISOString();
  upsertFundRequest({ ...req, status: "CLOSED", closedAt: now });
  emitAudit({
    action: "weeklyFund.adminClosed",
    subjectKind: "WeeklyFundRequest",
    subjectId: reqId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { reason: reason.trim(), previousStatus: req.status },
  });
  revalidateFundSurfaces(reqId);
  return { ok: true, id: reqId };
}
