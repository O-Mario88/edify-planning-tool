// Weekly Fund Engine.
//
// All state transitions for the weekly fund pipeline live here. UI
// components never mutate a request directly — they invoke an engine
// function which:
//   1. validates the `from → to` transition against an allow-list
//   2. enforces business rules (prior-week closed, funds available,
//      activity-on-plan, lead-approved, etc.)
//   3. updates the request, the funds-received ledger, and writes an
//      audit event in lockstep
//   4. emits notifications for the relevant audiences
//
// The engine is intentionally pure: it takes inputs, returns the
// updated entities and the audit + notification events to persist.
// A higher-level store/server-action layer wires the side effects.

import type {
  AccountabilityStatus,
  ApproverRole,
  BalanceReturn,
  BalanceReturnMethod,
  CountryMonthlyBudget,
  DisbursementMethod,
  DisbursementRecord,
  FiscalPeriod,
  FundAccountability,
  FundReceiptConfirmation,
  FundReconciliation,
  FundsReceivedRecord,
  Money,
  OverspendReason,
  OverspendThresholdFlag,
  ReconciliationOutcome,
  ReimbursementApprovalRoute,
  ReimbursementClaim,
  ReimbursementStatus,
  RequesterRole,
  RiskFlag,
  StaffFundBalance,
  WeeklyActivityAdjustment,
  WeeklyFundAuditAction,
  WeeklyFundAuditEvent,
  WeeklyFundBlocker,
  WeeklyFundNotification,
  WeeklyFundRequest,
  WeeklyFundRequestActivity,
  WeeklyFundRequestStatus,
  WeekOfMonth,
} from "./weekly-fund-types";
import { isValidId, ID_FORMATS } from "@/lib/intake/id-formats";

// ────────── Allowed transitions ───────────────────────────────────────
//
// Anything not listed here is rejected. Direct skips (e.g. SUBMITTED →
// DISBURSED, bypassing APPROVED) are deliberately impossible.

const TRANSITIONS: Record<WeeklyFundRequestStatus, WeeklyFundRequestStatus[]> = {
  AUTO_GENERATED: ["DRAFT", "CANCELLED"],
  DRAFT: ["SUBMITTED", "CANCELLED"],
  SUBMITTED: ["APPROVED", "RETURNED_TO_STAFF", "CANCELLED"],
  RETURNED_TO_STAFF: ["DRAFT", "SUBMITTED", "CANCELLED"],
  APPROVED: ["READY_TO_DISBURSE", "HOLD_NO_FUNDS_AVAILABLE", "BLOCKED_PRIOR_OUTSTANDING", "CANCELLED"],
  HOLD_NO_FUNDS_AVAILABLE: ["READY_TO_DISBURSE", "CANCELLED"],
  BLOCKED_PRIOR_OUTSTANDING: ["READY_TO_DISBURSE", "CANCELLED"],
  READY_TO_DISBURSE: ["DISBURSED", "CANCELLED"],
  DISBURSED: ["RECEIVED"],
  RECEIVED: ["IN_USE"],
  IN_USE: ["ACCOUNTABILITY_SUBMITTED"],
  ACCOUNTABILITY_SUBMITTED: ["ACCOUNTABILITY_APPROVED", "ACCOUNTABILITY_RETURNED"],
  ACCOUNTABILITY_RETURNED: ["ACCOUNTABILITY_SUBMITTED"],
  ACCOUNTABILITY_APPROVED: ["CLOSED"],
  CLOSED: ["ARCHIVED"],
  CANCELLED: ["ARCHIVED"],
  ARCHIVED: [],
};

export function isAllowedTransition(
  from: WeeklyFundRequestStatus,
  to: WeeklyFundRequestStatus,
): boolean {
  return TRANSITIONS[from]?.includes(to) ?? false;
}

// ────────── Money helpers ─────────────────────────────────────────────

export const ZERO_UGX: Money = { amount: 0, currency: "UGX" };

export function moneyAdd(a: Money, b: Money): Money {
  if (a.currency !== b.currency) throw new Error("currency mismatch");
  return { amount: a.amount + b.amount, currency: a.currency };
}

export function moneySub(a: Money, b: Money): Money {
  if (a.currency !== b.currency) throw new Error("currency mismatch");
  return { amount: a.amount - b.amount, currency: a.currency };
}

export function moneyGte(a: Money, b: Money): boolean {
  return a.currency === b.currency && a.amount >= b.amount;
}

export function formatMoney(m: Money): string {
  if (m.currency === "UGX") {
    if (m.amount >= 1_000_000_000) return `UGX ${(m.amount / 1_000_000_000).toFixed(2)}B`;
    if (m.amount >= 1_000_000)     return `UGX ${(m.amount / 1_000_000).toFixed(2)}M`;
    if (m.amount >= 1_000)         return `UGX ${(m.amount / 1_000).toFixed(0)}K`;
    return `UGX ${m.amount.toLocaleString()}`;
  }
  return `${m.currency} ${m.amount.toLocaleString()}`;
}

// ────────── Audit + notification builders ─────────────────────────────

let _auditSeq = 0;
function nextAuditId(): string {
  _auditSeq += 1;
  return `AUD-${Date.now()}-${_auditSeq}`;
}

function auditEvent(
  request: WeeklyFundRequest,
  action: WeeklyFundAuditAction,
  fromStatus: WeeklyFundRequestStatus | undefined,
  toStatus: WeeklyFundRequestStatus | undefined,
  actor: { id: string; name: string; role: WeeklyFundAuditEvent["actorRole"] },
  opts?: { note?: string; delta?: Money },
): WeeklyFundAuditEvent {
  return {
    id: nextAuditId(),
    weeklyFundRequestId: request.id,
    action,
    fromStatus,
    toStatus,
    actorId: actor.id,
    actorName: actor.name,
    actorRole: actor.role,
    at: new Date().toISOString(),
    note: opts?.note,
    delta: opts?.delta,
  };
}

let _notifSeq = 0;
function nextNotifId(): string {
  _notifSeq += 1;
  return `NTF-${Date.now()}-${_notifSeq}`;
}

function notify(
  request: WeeklyFundRequest,
  audience: { role: WeeklyFundNotification["audienceRole"]; userId: string },
  template: WeeklyFundNotification["template"],
  channel: WeeklyFundNotification["channel"] = "Inbox",
): WeeklyFundNotification {
  return {
    id: nextNotifId(),
    weeklyFundRequestId: request.id,
    audienceRole: audience.role,
    audienceUserId: audience.userId,
    channel,
    template,
    sentAt: new Date().toISOString(),
  };
}

// ────────── Engine result envelope ────────────────────────────────────

export type EngineResult<T> = {
  ok: boolean;
  data?: T;
  error?: string;
  audit: WeeklyFundAuditEvent[];
  notifications: WeeklyFundNotification[];
};

function fail<T>(error: string): EngineResult<T> {
  return { ok: false, error, audit: [], notifications: [] };
}

// ──────────────────────────────────────────────────────────────────────
// 1. generateWeeklyFundRequestsFromApprovedPlan
// ──────────────────────────────────────────────────────────────────────
//
// Splits an approved monthly plan into 4 weekly requests per staff.
// The split is deterministic: each activity is bucketed into its
// scheduled week-of-month. Activities with no schedule fall into W4.
//
// Output: 4 WeeklyFundRequest objects in AUTO_GENERATED status.

export type PlanActivityInput = {
  id: string;
  staffId: string;
  staffName: string;
  staffRole: WeeklyFundRequest["staffRole"];
  district: string;
  programLeadId: string;
  programLeadName: string;
  countryId: string;
  monthlyPlanId: string;
  weekOfMonth: WeekOfMonth;
  activity: WeeklyFundRequestActivity;
};

export function generateWeeklyFundRequestsFromApprovedPlan(
  planActivities: PlanActivityInput[],
  period: Omit<FiscalPeriod, "weekOfMonth" | "weekStartIso" | "weekEndIso">,
  weekRanges: Record<WeekOfMonth, { startIso: string; endIso: string }>,
): EngineResult<WeeklyFundRequest[]> {
  if (planActivities.length === 0) {
    return fail("No plan activities to split");
  }

  // group by staff × week
  const grouped = new Map<string, PlanActivityInput[]>();
  for (const row of planActivities) {
    const key = `${row.staffId}::${row.weekOfMonth}`;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(row);
  }

  const out: WeeklyFundRequest[] = [];
  const audit: WeeklyFundAuditEvent[] = [];
  const notifications: WeeklyFundNotification[] = [];

  for (const [key, rows] of grouped.entries()) {
    const [, weekStr] = key.split("::");
    const weekOfMonth = Number(weekStr) as WeekOfMonth;
    const sample = rows[0];
    const range = weekRanges[weekOfMonth];

    const activities = rows.map((r) => r.activity);
    const total = activities.reduce<Money>(
      (acc, a) => moneyAdd(acc, a.totalCost),
      ZERO_UGX,
    );

    const req: WeeklyFundRequest = {
      id: `WFR-${period.monthIso}-W${weekOfMonth}-${sample.staffId}`,
      staffId: sample.staffId,
      staffName: sample.staffName,
      staffRole: sample.staffRole,
      district: sample.district,
      programLeadId: sample.programLeadId,
      programLeadName: sample.programLeadName,
      countryId: sample.countryId,
      monthlyPlanId: sample.monthlyPlanId,
      period: {
        ...period,
        weekOfMonth,
        weekStartIso: range.startIso,
        weekEndIso: range.endIso,
      },
      status: "AUTO_GENERATED",
      plannedAmount: total,
      requestedAmount: total,
      activities,
      adjustments: [],
      flags: [],
      notes: "",
      source: "AUTO_FROM_PLAN",
    };
    out.push(req);

    audit.push(
      auditEvent(req, "AUTO_GENERATED", undefined, "AUTO_GENERATED",
        { id: "SYSTEM", name: "System", role: "System" },
        { note: `Auto-split from approved monthly plan ${sample.monthlyPlanId}` }),
    );
    notifications.push(
      notify(req, { role: "Staff", userId: sample.staffId }, "REQUEST_AUTO_GENERATED"),
    );
  }

  return { ok: true, data: out, audit, notifications };
}

// ──────────────────────────────────────────────────────────────────────
// 2. calculateWeeklyFundRequestTotal
// ──────────────────────────────────────────────────────────────────────

export function calculateWeeklyFundRequestTotal(
  req: Pick<WeeklyFundRequest, "activities">,
): Money {
  if (req.activities.length === 0) return ZERO_UGX;
  return req.activities
    .filter((a) => a.status !== "Cancelled")
    .reduce<Money>((acc, a) => moneyAdd(acc, a.totalCost), ZERO_UGX);
}

// ──────────────────────────────────────────────────────────────────────
// 3. checkWeeklyFundRequestEligibility
// ──────────────────────────────────────────────────────────────────────
//
// Returns the blockers that would prevent moving the request forward.
// Empty array means cleared.

export type EligibilityContext = {
  priorWeekClosed: boolean;        // last week's request status === CLOSED
  fundsAvailableAtCountry: Money;  // sum of available balances in country
  planActivityIds: Set<string>;    // activity ids on the approved plan
  costTolerancePct: number;        // e.g. 10 → ±10 % vs. planned
};

export function checkWeeklyFundRequestEligibility(
  req: WeeklyFundRequest,
  ctx: EligibilityContext,
): WeeklyFundBlocker[] {
  const blockers: WeeklyFundBlocker[] = [];

  if (!ctx.priorWeekClosed) {
    blockers.push("PRIOR_WEEK_NOT_CLOSED");
  }

  if (!moneyGte(ctx.fundsAvailableAtCountry, req.requestedAmount)) {
    blockers.push("FUNDS_NOT_RECEIVED_AT_COUNTRY");
  }

  const planned = req.plannedAmount.amount;
  if (planned > 0) {
    const deltaPct = Math.abs(req.requestedAmount.amount - planned) / planned * 100;
    if (deltaPct > ctx.costTolerancePct) {
      blockers.push("OVER_PLAN_TOLERANCE");
    }
  }

  for (const act of req.activities) {
    if (act.status === "Cancelled") continue;
    if (!ctx.planActivityIds.has(act.originPlanLineId)) {
      blockers.push("ACTIVITY_NOT_ON_APPROVED_PLAN");
      break;
    }
  }

  return blockers;
}

// ──────────────────────────────────────────────────────────────────────
// 4. confirmWeeklyFundRequest (Staff submit)
// ──────────────────────────────────────────────────────────────────────

export function confirmWeeklyFundRequest(
  req: WeeklyFundRequest,
  staff: { id: string; name: string },
  opts?: { adjustments?: WeeklyActivityAdjustment[]; note?: string },
): EngineResult<WeeklyFundRequest> {
  if (!isAllowedTransition(req.status, "SUBMITTED")) {
    return fail(`Cannot submit from status ${req.status}`);
  }
  const adjustments = opts?.adjustments ?? [];
  const newTotal = calculateWeeklyFundRequestTotal({
    activities: req.activities,
  });
  const next: WeeklyFundRequest = {
    ...req,
    status: "SUBMITTED",
    submittedAt: new Date().toISOString(),
    adjustments: [...req.adjustments, ...adjustments],
    requestedAmount: newTotal,
    notes: opts?.note ?? req.notes,
  };
  const audit = [
    auditEvent(next, "SUBMITTED", req.status, "SUBMITTED",
      { id: staff.id, name: staff.name, role: "Staff" },
      { note: opts?.note }),
  ];
  const notifications: WeeklyFundNotification[] = [
    notify(next, { role: "ProgramLead", userId: req.programLeadId }, "REQUEST_AUTO_GENERATED"),
  ];
  return { ok: true, data: next, audit, notifications };
}

// ──────────────────────────────────────────────────────────────────────
// 5. approveWeeklyFundRequestByLead
// ──────────────────────────────────────────────────────────────────────

export function approveWeeklyFundRequestByLead(
  req: WeeklyFundRequest,
  lead: { id: string; name: string },
  opts?: { note?: string },
): EngineResult<WeeklyFundRequest> {
  if (!isAllowedTransition(req.status, "APPROVED")) {
    return fail(`Cannot approve from status ${req.status}`);
  }
  const next: WeeklyFundRequest = {
    ...req,
    status: "APPROVED",
    approvedAt: new Date().toISOString(),
    approvedByLeadId: lead.id,
  };
  const audit = [
    auditEvent(next, "APPROVED", req.status, "APPROVED",
      { id: lead.id, name: lead.name, role: "ProgramLead" },
      { note: opts?.note }),
  ];
  const notifications: WeeklyFundNotification[] = [
    notify(next, { role: "Accountant", userId: "ACCOUNTANT" }, "REQUEST_APPROVED"),
    notify(next, { role: "Staff", userId: req.staffId }, "REQUEST_APPROVED"),
  ];
  return { ok: true, data: next, audit, notifications };
}

// ──────────────────────────────────────────────────────────────────────
// 6. returnWeeklyFundRequestByLead
// ──────────────────────────────────────────────────────────────────────

export function returnWeeklyFundRequestByLead(
  req: WeeklyFundRequest,
  lead: { id: string; name: string },
  reason: string,
): EngineResult<WeeklyFundRequest> {
  if (!reason || reason.trim().length < 5) {
    return fail("Return reason required (min 5 chars)");
  }
  if (!isAllowedTransition(req.status, "RETURNED_TO_STAFF")) {
    return fail(`Cannot return from status ${req.status}`);
  }
  const next: WeeklyFundRequest = {
    ...req,
    status: "RETURNED_TO_STAFF",
  };
  const audit = [
    auditEvent(next, "RETURNED", req.status, "RETURNED_TO_STAFF",
      { id: lead.id, name: lead.name, role: "ProgramLead" },
      { note: reason }),
  ];
  const notifications: WeeklyFundNotification[] = [
    notify(next, { role: "Staff", userId: req.staffId }, "REQUEST_RETURNED"),
  ];
  return { ok: true, data: next, audit, notifications };
}

// ──────────────────────────────────────────────────────────────────────
// 7. confirmFundsReceived (Accountant)
// ──────────────────────────────────────────────────────────────────────
//
// Records that money has actually landed at the country office. This
// is the gate that flips approved requests from HOLD_NO_FUNDS_AVAILABLE
// to READY_TO_DISBURSE.

export function confirmFundsReceived(
  input: Omit<FundsReceivedRecord, "id" | "confirmedAt" | "totalAllocated" | "availableBalance"> & {
    accountant: { id: string; name: string };
  },
): EngineResult<FundsReceivedRecord> {
  const id = `FR-${input.monthLabel.replace(/\s/g, "-")}-${Math.floor(Math.random() * 9000 + 1000)}`;
  const record: FundsReceivedRecord = {
    id,
    countryId: input.countryId,
    receivedOnIso: input.receivedOnIso,
    fromSource: input.fromSource,
    reference: input.reference,
    totalReceived: input.totalReceived,
    totalAllocated: ZERO_UGX,
    availableBalance: input.totalReceived,
    monthLabel: input.monthLabel,
    notes: input.notes,
    confirmedByAccountantId: input.accountant.id,
    confirmedAt: new Date().toISOString(),
  };
  return {
    ok: true,
    data: record,
    audit: [],
    notifications: [],
  };
}

// ──────────────────────────────────────────────────────────────────────
// 8. disburseWeeklyFundRequest (Accountant)
// ──────────────────────────────────────────────────────────────────────

export type DisbursementInput = {
  amount: Money;
  method: DisbursementMethod;
  reference: string;
  fundsReceivedId: string;
  fundsAvailable: Money;            // current avail on that batch
  accountant: { id: string; name: string };
  note?: string;
  priorWeekClosed: boolean;
  overrideAccountabilityGate?: { reason: string };  // audited override
};

export function disburseWeeklyFundRequest(
  req: WeeklyFundRequest,
  input: DisbursementInput,
): EngineResult<{ request: WeeklyFundRequest; disbursement: DisbursementRecord }> {
  if (req.status !== "APPROVED" && req.status !== "READY_TO_DISBURSE" &&
      req.status !== "HOLD_NO_FUNDS_AVAILABLE" && req.status !== "BLOCKED_PRIOR_OUTSTANDING") {
    return fail(`Cannot disburse from status ${req.status}`);
  }
  if (!moneyGte(input.fundsAvailable, input.amount)) {
    return fail("Insufficient funds on selected receipt batch");
  }
  if (!moneyGte(req.requestedAmount, input.amount)) {
    return fail("Disbursement exceeds requested amount");
  }
  if (!input.priorWeekClosed && !input.overrideAccountabilityGate) {
    return fail("Prior week not closed — accountability gate blocks release");
  }

  const dsbId = `DSB-${req.period.monthIso}-W${req.period.weekOfMonth}-${Math.floor(Math.random() * 9000 + 1000)}`;
  const disbursement: DisbursementRecord = {
    id: dsbId,
    weeklyFundRequestId: req.id,
    fundsReceivedId: input.fundsReceivedId,
    staffId: req.staffId,
    staffName: req.staffName,
    amount: input.amount,
    method: input.method,
    reference: input.reference,
    disbursedAt: new Date().toISOString(),
    disbursedByAccountantId: input.accountant.id,
    disbursedByAccountantName: input.accountant.name,
    reversed: false,
  };

  const next: WeeklyFundRequest = {
    ...req,
    status: "DISBURSED",
    disbursedAt: disbursement.disbursedAt,
    disbursedByAccountantId: input.accountant.id,
    disbursedAmount: input.amount,
    flags: req.flags.filter((f) => f !== "FUNDS_NOT_RECEIVED_AT_COUNTRY" && f !== "PRIOR_WEEK_NOT_CLOSED"),
  };

  const audit: WeeklyFundAuditEvent[] = [
    auditEvent(next, "DISBURSED", req.status, "DISBURSED",
      { id: input.accountant.id, name: input.accountant.name, role: "Accountant" },
      { note: input.note, delta: input.amount }),
  ];
  if (input.overrideAccountabilityGate) {
    audit.push(
      auditEvent(next, "OVERRIDE", req.status, "DISBURSED",
        { id: input.accountant.id, name: input.accountant.name, role: "Accountant" },
        { note: `Accountability gate override: ${input.overrideAccountabilityGate.reason}` }),
    );
  }

  const notifications: WeeklyFundNotification[] = [
    notify(next, { role: "Staff", userId: req.staffId }, "REQUEST_DISBURSED"),
    notify(next, { role: "ProgramLead", userId: req.programLeadId }, "REQUEST_DISBURSED"),
  ];

  return {
    ok: true,
    data: { request: next, disbursement },
    audit,
    notifications,
  };
}

// ──────────────────────────────────────────────────────────────────────
// 9. confirmStaffReceipt
// ──────────────────────────────────────────────────────────────────────

export function confirmStaffReceipt(
  req: WeeklyFundRequest,
  disbursement: DisbursementRecord,
  staff: { id: string; name: string },
  opts?: { note?: string },
): EngineResult<{ request: WeeklyFundRequest; disbursement: DisbursementRecord }> {
  if (!isAllowedTransition(req.status, "RECEIVED")) {
    return fail(`Cannot confirm receipt from status ${req.status}`);
  }
  const nextDisbursement: DisbursementRecord = {
    ...disbursement,
    receiptConfirmedByStaffAt: new Date().toISOString(),
    receiptNote: opts?.note,
  };
  const next: WeeklyFundRequest = {
    ...req,
    status: "RECEIVED",
    receivedAt: nextDisbursement.receiptConfirmedByStaffAt,
  };
  const audit = [
    auditEvent(next, "RECEIPT_CONFIRMED", req.status, "RECEIVED",
      { id: staff.id, name: staff.name, role: "Staff" },
      { note: opts?.note }),
  ];
  const notifications: WeeklyFundNotification[] = [
    notify(next, { role: "Accountant", userId: disbursement.disbursedByAccountantId }, "RECEIPT_REMINDER"),
  ];
  return { ok: true, data: { request: next, disbursement: nextDisbursement }, audit, notifications };
}

// ──────────────────────────────────────────────────────────────────────
// 10. submitWeeklyFundAccountability
// ──────────────────────────────────────────────────────────────────────

export type AccountabilitySubmission = {
  accountedAmount: Money;
  returnedAmount: Money;
  receipts: { activityId: string; receiptRef: string; amount: Money }[];
  note?: string;
};

export function submitWeeklyFundAccountability(
  req: WeeklyFundRequest,
  staff: { id: string; name: string },
  submission: AccountabilitySubmission,
): EngineResult<WeeklyFundRequest> {
  if (req.status !== "RECEIVED" && req.status !== "IN_USE" && req.status !== "ACCOUNTABILITY_RETURNED") {
    return fail(`Cannot submit accountability from status ${req.status}`);
  }
  if (!req.disbursedAmount) {
    return fail("Request has no disbursement on record");
  }
  const sum = moneyAdd(submission.accountedAmount, submission.returnedAmount);
  if (sum.amount !== req.disbursedAmount.amount) {
    return fail(`Accounted + returned (${formatMoney(sum)}) must equal disbursed (${formatMoney(req.disbursedAmount)})`);
  }
  if (submission.receipts.length === 0) {
    return fail("At least one receipt is required");
  }
  const next: WeeklyFundRequest = {
    ...req,
    status: "ACCOUNTABILITY_SUBMITTED",
    accountedAmount: submission.accountedAmount,
    returnedAmount: submission.returnedAmount,
    accountabilitySubmittedAt: new Date().toISOString(),
    flags: req.flags.filter((f) => f !== "MISSING_RECEIPTS"),
  };
  const audit = [
    auditEvent(next, "ACCOUNTABILITY_SUBMITTED", req.status, "ACCOUNTABILITY_SUBMITTED",
      { id: staff.id, name: staff.name, role: "Staff" },
      { note: submission.note, delta: submission.accountedAmount }),
  ];
  const notifications: WeeklyFundNotification[] = [
    notify(next, { role: "ProgramLead", userId: req.programLeadId }, "ACCOUNTABILITY_DUE"),
  ];
  return { ok: true, data: next, audit, notifications };
}

// ──────────────────────────────────────────────────────────────────────
// 11. approveWeeklyFundAccountability
// ──────────────────────────────────────────────────────────────────────

export function approveWeeklyFundAccountability(
  req: WeeklyFundRequest,
  lead: { id: string; name: string },
  opts?: { note?: string },
): EngineResult<WeeklyFundRequest> {
  if (!isAllowedTransition(req.status, "ACCOUNTABILITY_APPROVED")) {
    return fail(`Cannot approve accountability from status ${req.status}`);
  }
  const approvedAt = new Date().toISOString();
  // Auto-close to terminal state.
  const closed: WeeklyFundRequest = {
    ...req,
    status: "CLOSED",
    accountabilityApprovedAt: approvedAt,
    closedAt: approvedAt,
  };
  const audit: WeeklyFundAuditEvent[] = [
    auditEvent(closed, "ACCOUNTABILITY_APPROVED", req.status, "ACCOUNTABILITY_APPROVED",
      { id: lead.id, name: lead.name, role: "ProgramLead" },
      { note: opts?.note }),
    auditEvent(closed, "CLOSED", "ACCOUNTABILITY_APPROVED", "CLOSED",
      { id: lead.id, name: lead.name, role: "ProgramLead" }),
  ];
  const notifications: WeeklyFundNotification[] = [
    notify(closed, { role: "Staff", userId: req.staffId }, "ACCOUNTABILITY_APPROVED"),
    notify(closed, { role: "Accountant", userId: "ACCOUNTANT" }, "ACCOUNTABILITY_APPROVED"),
  ];
  return { ok: true, data: closed, audit, notifications };
}

// ──────────────────────────────────────────────────────────────────────
// Auto-routing: requester role → approver
// ──────────────────────────────────────────────────────────────────────
//
// CCEO weekly fund requests always go to the assigned Program Lead.
// Everyone else (PL / IA / Accountant / Special Projects / Admin) goes
// straight to the Country Director. The Accountant only ever sees
// requests that already carry an approver signature.

export function resolveApprover(requester: RequesterRole): ApproverRole {
  if (requester === "CCEO") return "ProgramLead";
  return "CountryDirector";
}

// ──────────────────────────────────────────────────────────────────────
// Risk-flag computation
// ──────────────────────────────────────────────────────────────────────

export type RiskComputeContext = {
  priorWeekClosed: boolean;
  priorWeekMissingReceipts: boolean;
  priorWeekMissingSalesforceIds: boolean;
  staffOnLeave: boolean;
};

export function computeRiskFlags(
  req: WeeklyFundRequest,
  ctx: RiskComputeContext,
): RiskFlag[] {
  const flags: RiskFlag[] = [];

  if (!ctx.priorWeekClosed || ctx.priorWeekMissingReceipts) {
    flags.push("PreviousAccountabilityPending");
  }
  if (ctx.priorWeekMissingSalesforceIds) {
    flags.push("MissingSalesforceIds");
  }
  if (ctx.staffOnLeave) {
    flags.push("StaffOnLeave");
  }

  if (req.plannedAmount.amount > 0) {
    const delta = req.requestedAmount.amount - req.plannedAmount.amount;
    const pct = (Math.abs(delta) / req.plannedAmount.amount) * 100;
    if (pct > 10 && delta > 0) {
      flags.push("ExceedsApprovedWeeklyPlan");
    }
  }
  if (req.adjustments.some((a) => a.type === "MovedFromAnotherWeek")) {
    flags.push("ActivityMovedAfterApproval");
  }

  const transport = req.activities.reduce(
    (a, x) => a + x.costBreakdown.transport.amount, 0);
  if (req.requestedAmount.amount > 0 &&
      transport / req.requestedAmount.amount > 0.35) {
    flags.push("HighTransportVariance");
  }

  const allowance = req.activities.reduce(
    (a, x) => a + x.costBreakdown.allowance.amount, 0);
  if (req.requestedAmount.amount > 0 &&
      allowance / req.requestedAmount.amount > 0.30) {
    flags.push("OvernightCostUnusual");
  }

  const clusterMissing = req.activities.some(
    (a) =>
      (a.kind === "Cluster" || a.kind === "TeacherTraining") && !a.note,
  );
  if (clusterMissing) {
    flags.push("MissingParticipantCount");
  }

  return Array.from(new Set(flags));
}

// ──────────────────────────────────────────────────────────────────────
// Refined disbursement: full modal payload + Hold + Partial + Escalate
// ──────────────────────────────────────────────────────────────────────

export type DisbursementFormPayload = {
  amount: Money;
  method: DisbursementMethod;
  reference: string;
  disbursedOnIso: string;
  notes?: string;
  fundsReceivedId: string;
};

export function disburseFromForm(
  req: WeeklyFundRequest,
  form: DisbursementFormPayload,
  accountant: { id: string; name: string },
  ctx: { fundsAvailable: Money; priorWeekClosed: boolean },
): EngineResult<{ request: WeeklyFundRequest; disbursement: DisbursementRecord }> {
  return disburseWeeklyFundRequest(req, {
    amount: form.amount,
    method: form.method,
    reference: form.reference,
    fundsReceivedId: form.fundsReceivedId,
    fundsAvailable: ctx.fundsAvailable,
    accountant,
    note: form.notes,
    priorWeekClosed: ctx.priorWeekClosed,
  });
}

export function holdDisbursement(
  req: WeeklyFundRequest,
  accountant: { id: string; name: string },
  reason: string,
): EngineResult<WeeklyFundRequest> {
  if (!isAllowedTransition(req.status, "HOLD_NO_FUNDS_AVAILABLE")) {
    return fail(`Cannot hold from status ${req.status}`);
  }
  const next: WeeklyFundRequest = {
    ...req,
    status: "HOLD_NO_FUNDS_AVAILABLE",
    flags: Array.from(new Set([...req.flags, "FUNDS_NOT_RECEIVED_AT_COUNTRY" as WeeklyFundBlocker])),
  };
  const audit = [
    auditEvent(next, "BLOCKER_RAISED", req.status, "HOLD_NO_FUNDS_AVAILABLE",
      { id: accountant.id, name: accountant.name, role: "Accountant" },
      { note: reason }),
  ];
  return { ok: true, data: next, audit, notifications: [] };
}

export function partialDisburse(
  req: WeeklyFundRequest,
  form: DisbursementFormPayload,
  accountant: { id: string; name: string },
  ctx: { fundsAvailable: Money; priorWeekClosed: boolean },
): EngineResult<{ request: WeeklyFundRequest; disbursement: DisbursementRecord }> {
  if (form.amount.amount >= req.requestedAmount.amount) {
    return fail("Partial disbursement must be less than requested amount");
  }
  const result = disburseFromForm(req, form, accountant, ctx);
  if (!result.ok || !result.data) return result;
  const outstanding = formatMoney({
    amount: req.requestedAmount.amount - form.amount.amount,
    currency: req.requestedAmount.currency,
  });
  return {
    ...result,
    data: {
      ...result.data,
      request: {
        ...result.data.request,
        notes: `${result.data.request.notes ? result.data.request.notes + " · " : ""}Partial — outstanding ${outstanding}`,
      },
    },
  };
}

export function escalateToCountryDirector(
  req: WeeklyFundRequest,
  accountant: { id: string; name: string },
  reason: string,
): EngineResult<WeeklyFundRequest> {
  if (req.status !== "APPROVED" && req.status !== "HOLD_NO_FUNDS_AVAILABLE") {
    return fail(`Cannot escalate from status ${req.status}`);
  }
  const next: WeeklyFundRequest = {
    ...req,
    approverRole: "CountryDirector",
  };
  const audit = [
    auditEvent(next, "OVERRIDE", req.status, req.status,
      { id: accountant.id, name: accountant.name, role: "Accountant" },
      { note: `Escalated to CD: ${reason}` }),
  ];
  return { ok: true, data: next, audit, notifications: [] };
}

// ──────────────────────────────────────────────────────────────────────
// Country Monthly Budget approval (RVP)
// ──────────────────────────────────────────────────────────────────────

export function approveCountryMonthlyBudget(
  budget: CountryMonthlyBudget,
  rvp: { id: string; name: string },
  opts?: { conditions?: string },
): CountryMonthlyBudget {
  return {
    ...budget,
    status: opts?.conditions ? "APPROVED_WITH_CONDITIONS" : "APPROVED",
    approvedByRvpId: rvp.id,
    approvedByRvpName: rvp.name,
    approvedAt: new Date().toISOString(),
    conditions: opts?.conditions,
  };
}

export function returnCountryMonthlyBudget(
  budget: CountryMonthlyBudget,
  rvp: { id: string; name: string },
  reason: string,
): CountryMonthlyBudget {
  return {
    ...budget,
    status: "RETURNED",
    notes: `${budget.notes ? budget.notes + " · " : ""}Returned by RVP: ${reason}`,
    approvedByRvpId: rvp.id,
    approvedByRvpName: rvp.name,
  };
}

// ──────────────────────────────────────────────────────────────────────
// Receipt Confirmation
// ──────────────────────────────────────────────────────────────────────
//
// After the accountant marks Disbursed, the system creates an
// "Awaiting" receipt confirmation. The staff member then either
// confirms (status → Confirmed) or disputes it (status → Disputed).
// Disputed receipts must be resolved by the accountant before the
// accountability section unlocks.

export function confirmReceipt(
  receipt: FundReceiptConfirmation,
  staff: { id: string; name: string },
  amountReceivedUgx?: number,
): EngineResult<FundReceiptConfirmation> {
  if (receipt.status !== "Awaiting") {
    return fail(`Cannot confirm receipt from status ${receipt.status}`);
  }
  if (receipt.staffId !== staff.id) {
    return fail("Only the receiving staff member can confirm");
  }
  const actualReceived = amountReceivedUgx ?? receipt.amountDisbursedUgx;
  const isDiscrepancy = actualReceived !== receipt.amountDisbursedUgx;
  const next: FundReceiptConfirmation = {
    ...receipt,
    amountReceivedUgx: actualReceived,
    confirmedAt: new Date().toISOString(),
    status: isDiscrepancy ? "Disputed" : "Confirmed",
    discrepancyAmountUgx: isDiscrepancy
      ? receipt.amountDisbursedUgx - actualReceived
      : undefined,
  };
  return { ok: true, data: next, audit: [], notifications: [] };
}

export function disputeReceipt(
  receipt: FundReceiptConfirmation,
  staff: { id: string; name: string },
  reportedAmountUgx: number,
  comment: string,
): EngineResult<FundReceiptConfirmation> {
  if (receipt.status !== "Awaiting") {
    return fail(`Cannot dispute receipt from status ${receipt.status}`);
  }
  if (!comment || comment.trim().length < 5) {
    return fail("Dispute comment required (min 5 chars)");
  }
  const next: FundReceiptConfirmation = {
    ...receipt,
    amountReceivedUgx: reportedAmountUgx,
    confirmedAt: new Date().toISOString(),
    status: "Disputed",
    discrepancyAmountUgx: receipt.amountDisbursedUgx - reportedAmountUgx,
    comment,
  };
  return { ok: true, data: next, audit: [], notifications: [] };
}

// ──────────────────────────────────────────────────────────────────────
// Accountability — NetSuite Expense ID-based
// ──────────────────────────────────────────────────────────────────────

// Opens the accountability record once the receipt is confirmed.
// Status flips from "Not Open" → "Open" and the staff member can now
// submit a NetSuite Expense ID.
export function openAccountability(
  acc: FundAccountability,
): EngineResult<FundAccountability> {
  if (acc.status !== "Not Open") {
    return fail(`Accountability already open (status ${acc.status})`);
  }
  return {
    ok: true,
    data: { ...acc, status: "Open" },
    audit: [],
    notifications: [],
  };
}

export type AccountabilitySubmissionPayload = {
  netsuiteExpenseId: string;
  amountSpentUgx: number;
  accountabilityNote?: string;
  evidenceLinks?: string[];
};

// Staff submits the NetSuite Expense ID + amount spent. The engine
// auto-computes balance-to-return / overspend. Triggers status →
// "NetSuite ID Submitted" so the accountant queue picks it up.
export function submitAccountability(
  acc: FundAccountability,
  staff: { id: string; name: string },
  payload: AccountabilitySubmissionPayload,
): EngineResult<FundAccountability> {
  if (acc.status !== "Open" && acc.status !== "Returned for Correction") {
    return fail(`Cannot submit accountability from status ${acc.status}`);
  }
  if (acc.staffId !== staff.id) {
    return fail("Only the staff owner can submit accountability");
  }
  const id = payload.netsuiteExpenseId?.trim();
  if (!id || !isValidId("expense", id)) {
    return fail(`NetSuite Expense ID required (${ID_FORMATS.expense.hint})`);
  }
  if (!Number.isFinite(payload.amountSpentUgx) || payload.amountSpentUgx < 0) {
    return fail("Amount spent must be a non-negative number");
  }

  const spent = payload.amountSpentUgx;
  const disbursed = acc.amountDisbursedUgx;
  const balance = Math.max(disbursed - spent, 0);
  const overspend = Math.max(spent - disbursed, 0);

  return {
    ok: true,
    data: {
      ...acc,
      netsuiteExpenseId: id,
      amountSpentUgx: spent,
      balanceToReturnUgx: balance,
      overspendUgx: overspend,
      accountabilityNote: payload.accountabilityNote,
      evidenceLinks: payload.evidenceLinks,
      status: "NetSuite ID Submitted",
      submittedAt: new Date().toISOString(),
    },
    audit: [],
    notifications: [],
  };
}

// Accountant moves the record to Under Review on open.
export function reviewAccountability(
  acc: FundAccountability,
  accountant: { id: string; name: string },
): EngineResult<FundAccountability> {
  if (acc.status !== "NetSuite ID Submitted") {
    return fail(`Cannot review from status ${acc.status}`);
  }
  return {
    ok: true,
    data: {
      ...acc,
      status: "Under Accountant Review",
      reviewedBy: accountant.id,
    },
    audit: [],
    notifications: [],
  };
}

// Accountant approves the accountability. Closes the loop and unlocks
// future fund releases for this staff member.
export function approveAccountability(
  acc: FundAccountability,
  accountant: { id: string; name: string },
): EngineResult<FundAccountability> {
  if (acc.status !== "NetSuite ID Submitted" && acc.status !== "Under Accountant Review") {
    return fail(`Cannot approve from status ${acc.status}`);
  }
  if (!acc.netsuiteExpenseId) {
    return fail("Cannot approve without a NetSuite Expense ID on record");
  }
  return {
    ok: true,
    data: {
      ...acc,
      status: "Approved",
      reviewedBy: accountant.id,
      reviewedAt: new Date().toISOString(),
    },
    audit: [],
    notifications: [],
  };
}

// Accountant returns the accountability for correction (e.g. mis-typed
// NetSuite ID, missing receipt). Reason is mandatory.
export function returnAccountability(
  acc: FundAccountability,
  accountant: { id: string; name: string },
  reason: string,
): EngineResult<FundAccountability> {
  if (acc.status !== "NetSuite ID Submitted" && acc.status !== "Under Accountant Review") {
    return fail(`Cannot return from status ${acc.status}`);
  }
  if (!reason || reason.trim().length < 5) {
    return fail("Return reason required (min 5 chars)");
  }
  return {
    ok: true,
    data: {
      ...acc,
      status: "Returned for Correction",
      reviewedBy: accountant.id,
      reviewedAt: new Date().toISOString(),
      returnedReason: reason,
    },
    audit: [],
    notifications: [],
  };
}

// Gate: can this staff member receive a new disbursement? Only when
// every previous accountability is Approved or Closed.
export function accountabilityGateOpen(
  history: FundAccountability[],
): boolean {
  return history.every((a) => a.status === "Approved" || a.status === "Closed");
}

// ──────────────────────────────────────────────────────────────────────
// Reconciliation — the brain of the accountability flow
// ──────────────────────────────────────────────────────────────────────
//
// When staff submits accountability they paste a NetSuite Expense ID
// and enter the *amount spent* (reconciled from NetSuite). The engine
// then runs `reconcileAccountability` which:
//
//   • Computes the signed difference (spent − advanced)
//   • Picks the outcome: Fully Accounted / Balance To Return /
//     Reimbursement Due
//   • Auto-creates a BalanceReturn record when underspent
//   • Auto-creates a ReimbursementClaim when overspent — with the
//     correct approval route + threshold flag (15 % rule)
//
// The staff never fills a separate reimbursement form for an
// auto-created claim originating from this same activity.

// Threshold rule per spec: > 15 % overspend escalates to CD.
export const OVERSPEND_HIGH_THRESHOLD_PCT = 15;

export function computeOverspendThreshold(
  advancedUgx: number,
  spentUgx: number,
): { pct: number; flag: OverspendThresholdFlag } {
  if (advancedUgx <= 0 || spentUgx <= advancedUgx) {
    return { pct: 0, flag: "Normal" };
  }
  const pct = ((spentUgx - advancedUgx) / advancedUgx) * 100;
  if (pct > OVERSPEND_HIGH_THRESHOLD_PCT) {
    return { pct, flag: "RequiresCDReview" };
  }
  return { pct, flag: "Normal" };
}

export type ReconciliationInput = {
  fundRequestId: string;
  disbursementId: string;
  staffId: string;
  staffName: string;
  staffRole: ReimbursementClaim["staffRole"];
  weeklyPlanId?: string;
  activityTitle?: string;

  netsuiteExpenseId: string;
  advancedAmountUgx: number;
  amountReceivedUgx?: number;     // defaults to advanced when undefined
  amountSpentUgx: number;

  // Only required when amountSpent > advanced.
  overspendReason?: OverspendReason;
  overspendNote?: string;
  accountabilityNote?: string;
};

export type ReconciliationResult = {
  reconciliation: FundReconciliation;
  // Set when outcome === "Balance To Return"
  balanceReturn?: BalanceReturn;
  // Set when outcome === "Reimbursement Due"
  autoReimbursement?: ReimbursementClaim;
};

// Core function. Pure: returns the reconciliation + any side-effect
// records the caller should persist alongside it.
export function reconcileAccountability(
  input: ReconciliationInput,
): EngineResult<ReconciliationResult> {
  // ── Validation ────────────────────────────────────────────────────
  const id = input.netsuiteExpenseId?.trim();
  if (!id || !isValidId("expense", id)) {
    return fail(`NetSuite Expense ID required (${ID_FORMATS.expense.hint})`);
  }
  if (!Number.isFinite(input.amountSpentUgx) || input.amountSpentUgx < 0) {
    return fail("Amount spent must be a non-negative number");
  }
  if (!Number.isFinite(input.advancedAmountUgx) || input.advancedAmountUgx < 0) {
    return fail("Advanced amount must be a non-negative number");
  }

  const advanced = input.advancedAmountUgx;
  const spent = input.amountSpentUgx;
  const received = input.amountReceivedUgx ?? advanced;
  const diff = spent - advanced;

  // ── Outcome decision ──────────────────────────────────────────────
  let outcome: ReconciliationOutcome;
  let balanceToReturn = 0;
  let reimbursementDue = 0;

  if (diff === 0) {
    outcome = "Fully Accounted";
  } else if (diff < 0) {
    outcome = "Balance To Return";
    balanceToReturn = -diff;
  } else {
    outcome = "Reimbursement Due";
    reimbursementDue = diff;
    // Overspend path requires an overspend reason.
    if (!input.overspendReason) {
      return fail("Overspend reason is required when amount spent exceeds advanced");
    }
  }

  const { pct, flag } = computeOverspendThreshold(advanced, spent);
  const audit: WeeklyFundAuditEvent[] = [];
  const notifications: WeeklyFundNotification[] = [];

  // ── Build the reconciliation record ───────────────────────────────
  const reconciliationId = `RCN-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  const reconciliation: FundReconciliation = {
    id: reconciliationId,
    fundRequestId: input.fundRequestId,
    disbursementId: input.disbursementId,
    staffId: input.staffId,
    staffName: input.staffName,
    netsuiteExpenseId: id,
    advancedAmountUgx: advanced,
    amountReceivedUgx: received,
    amountSpentUgx: spent,
    differenceUgx: diff,
    outcome,
    balanceToReturnUgx: balanceToReturn,
    reimbursementDueUgx: reimbursementDue,
    overspendPct: pct,
    thresholdFlag: flag,
    overspendReason: input.overspendReason,
    overspendNote: input.overspendNote,
    accountabilityNote: input.accountabilityNote,
    status: "Submitted",
    submittedAt: new Date().toISOString(),
  };

  // ── Underspend → BalanceReturn record ─────────────────────────────
  let balanceReturn: BalanceReturn | undefined;
  if (outcome === "Balance To Return") {
    balanceReturn = {
      id: `BAL-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      fundReconciliationId: reconciliationId,
      fundRequestId: input.fundRequestId,
      staffId: input.staffId,
      staffName: input.staffName,
      amountUgx: balanceToReturn,
      status: "Pending",
      createdAt: new Date().toISOString(),
    };
    reconciliation.createdBalanceReturnId = balanceReturn.id;
  }

  // ── Overspend → auto-create ReimbursementClaim ────────────────────
  let autoReimbursement: ReimbursementClaim | undefined;
  if (outcome === "Reimbursement Due") {
    // Threshold rule: > 15 % escalates CCEO claims to CD instead of PL.
    const baseRoute = resolveReimbursementRoute(input.staffRole);
    const effectiveRoute: ReimbursementApprovalRoute =
      flag === "RequiresCDReview" ? "CountryDirector" : baseRoute;

    autoReimbursement = {
      id: `REIM-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      staffId: input.staffId,
      staffName: input.staffName,
      staffRole: input.staffRole,
      activityTitle: input.activityTitle,
      weeklyPlanId: input.weeklyPlanId,
      fundRequestId: input.fundRequestId,
      fundReconciliationId: reconciliationId,
      autoCreated: true,
      thresholdFlag: flag,
      amountSpentUgx: spent,
      amountPreviouslyDisbursedUgx: advanced,
      amountToReimburseUgx: reimbursementDue,
      reasonPersonalFundsUsed:
        input.overspendNote?.trim().length
          ? input.overspendNote.trim()
          : `Auto: overspend on advanced funds (${flag === "RequiresCDReview" ? "high overspend" : "within threshold"})`,
      overspendReason: input.overspendReason,
      netsuiteExpenseId: id,
      approvalRoute: effectiveRoute,
      status: "Submitted",
      submittedAt: new Date().toISOString(),
    };
    reconciliation.createdAutoReimbursementId = autoReimbursement.id;

    notifications.push({
      id: `NTF-${Date.now()}-AR`,
      weeklyFundRequestId: input.fundRequestId,
      audienceRole:
        effectiveRoute === "ProgramLead" ? "ProgramLead" : "Director",
      audienceUserId: "ROUTED",
      channel: "Inbox",
      template: "REQUEST_AUTO_GENERATED",
      sentAt: new Date().toISOString(),
    });
  }

  return {
    ok: true,
    data: { reconciliation, balanceReturn, autoReimbursement },
    audit,
    notifications,
  };
}

// Accountant confirms the staff actually returned the balance.
export function confirmBalanceReturn(
  balanceReturn: BalanceReturn,
  staff: { id: string; name: string },
  method: BalanceReturnMethod,
  reference?: string,
): EngineResult<BalanceReturn> {
  if (balanceReturn.status !== "Pending") {
    return fail(`Cannot confirm balance return from status ${balanceReturn.status}`);
  }
  if (balanceReturn.staffId !== staff.id) {
    return fail("Only the originating staff can declare the return method");
  }
  return {
    ok: true,
    data: {
      ...balanceReturn,
      method,
      reference,
      status: "Confirmed",
      confirmedAt: new Date().toISOString(),
    },
    audit: [],
    notifications: [],
  };
}

export function disputeBalanceReturn(
  balanceReturn: BalanceReturn,
  accountant: { id: string; name: string },
  comment: string,
): EngineResult<BalanceReturn> {
  if (balanceReturn.status !== "Pending" && balanceReturn.status !== "Confirmed") {
    return fail(`Cannot dispute from status ${balanceReturn.status}`);
  }
  if (!comment || comment.trim().length < 5) {
    return fail("Dispute comment required (min 5 chars)");
  }
  return {
    ok: true,
    data: { ...balanceReturn, status: "Disputed", comment },
    audit: [],
    notifications: [],
  };
}

// ──────────────────────────────────────────────────────────────────────
// Reimbursement Claims — staff used personal money
// ──────────────────────────────────────────────────────────────────────

// Auto-route the claim based on requester role.
//
//   • CCEO              → Program Lead first, then Accountant
//   • PL / IA / Acct / SP / Admin → Country Director, then Accountant
//
// (Accountant-only direct path is reserved for the rare case where the
// claim originates from an already-approved plan activity and only
// needs the NetSuite ID verified.)
export function resolveReimbursementRoute(
  staffRole: ReimbursementClaim["staffRole"],
): ReimbursementApprovalRoute {
  if (staffRole === "CCEO") return "ProgramLead";
  return "CountryDirector";
}

export type ReimbursementClaimPayload = {
  staffId: string;
  staffName: string;
  staffRole: ReimbursementClaim["staffRole"];
  activityId?: string;
  activityTitle?: string;
  weeklyPlanId?: string;
  fundRequestId?: string;
  amountSpentUgx: number;
  amountPreviouslyDisbursedUgx: number;
  reasonPersonalFundsUsed: string;
  netsuiteExpenseId: string;
  evidenceLinks?: string[];
};

// Staff submits a reimbursement claim. The engine validates fields,
// auto-routes based on role, and computes amount-to-reimburse.
export function submitReimbursementClaim(
  payload: ReimbursementClaimPayload,
): EngineResult<ReimbursementClaim> {
  const id = payload.netsuiteExpenseId?.trim();
  if (!id || !isValidId("expense", id)) {
    return fail(`NetSuite Expense ID required for reimbursement claims (${ID_FORMATS.expense.hint})`);
  }
  if (!Number.isFinite(payload.amountSpentUgx) || payload.amountSpentUgx <= 0) {
    return fail("Amount spent must be greater than zero");
  }
  if (!payload.reasonPersonalFundsUsed || payload.reasonPersonalFundsUsed.trim().length < 5) {
    return fail("Reason for using personal funds required (min 5 chars)");
  }

  const toReimburse = Math.max(
    payload.amountSpentUgx - (payload.amountPreviouslyDisbursedUgx ?? 0),
    0,
  );
  if (toReimburse <= 0) {
    return fail("Nothing to reimburse — previously disbursed amount covers the spend");
  }

  const claim: ReimbursementClaim = {
    id: `REIM-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    staffId: payload.staffId,
    staffName: payload.staffName,
    staffRole: payload.staffRole,
    activityId: payload.activityId,
    activityTitle: payload.activityTitle,
    weeklyPlanId: payload.weeklyPlanId,
    fundRequestId: payload.fundRequestId,
    amountSpentUgx: payload.amountSpentUgx,
    amountPreviouslyDisbursedUgx: payload.amountPreviouslyDisbursedUgx ?? 0,
    amountToReimburseUgx: toReimburse,
    reasonPersonalFundsUsed: payload.reasonPersonalFundsUsed.trim(),
    netsuiteExpenseId: id,
    evidenceLinks: payload.evidenceLinks,
    approvalRoute: resolveReimbursementRoute(payload.staffRole),
    status: "Submitted",
    submittedAt: new Date().toISOString(),
  };

  return { ok: true, data: claim, audit: [], notifications: [] };
}

// Supervisor (PL for CCEO, CD for others) verifies the activity was
// valid before the claim queues for the accountant.
export function approveReimbursementBySupervisor(
  claim: ReimbursementClaim,
  supervisor: { id: string; name: string },
): EngineResult<ReimbursementClaim> {
  if (claim.status !== "Submitted" && claim.status !== "Supervisor Review") {
    return fail(`Cannot approve from status ${claim.status}`);
  }
  return {
    ok: true,
    data: {
      ...claim,
      status: "Queued for Accountant",
      approvedBy: supervisor.id,
      approvedAt: new Date().toISOString(),
    },
    audit: [],
    notifications: [],
  };
}

export function returnReimbursement(
  claim: ReimbursementClaim,
  reviewer: { id: string; name: string },
  reason: string,
): EngineResult<ReimbursementClaim> {
  if (claim.status === "Reimbursed" || claim.status === "Closed") {
    return fail(`Cannot return from status ${claim.status}`);
  }
  if (!reason || reason.trim().length < 5) {
    return fail("Return reason required (min 5 chars)");
  }
  return {
    ok: true,
    data: {
      ...claim,
      status: "Returned for Correction",
      returnedReason: reason,
      approvedBy: reviewer.id,
    },
    audit: [],
    notifications: [],
  };
}

// Accountant releases reimbursement funds. Requires the NetSuite
// Expense ID to be present.
export function reimburseClaim(
  claim: ReimbursementClaim,
  accountant: { id: string; name: string },
  transactionReference: string,
): EngineResult<ReimbursementClaim> {
  if (claim.status !== "Queued for Accountant" && claim.status !== "Approved for Reimbursement") {
    return fail(`Cannot reimburse from status ${claim.status}`);
  }
  if (!claim.netsuiteExpenseId) {
    return fail("NetSuite Expense ID required before reimbursing");
  }
  if (!transactionReference || transactionReference.trim().length < 4) {
    return fail("Transaction reference required (min 4 chars)");
  }
  return {
    ok: true,
    data: {
      ...claim,
      status: "Reimbursed",
      reimbursedBy: accountant.id,
      reimbursedAt: new Date().toISOString(),
      transactionReference: transactionReference.trim(),
    },
    audit: [],
    notifications: [],
  };
}

// Gate the next disbursement on every prior accountability being
// Approved AND every reimbursement claim being Reimbursed or Closed.
export function postDisbursementGateOpen(
  accountabilities: FundAccountability[],
  reimbursements: ReimbursementClaim[],
): boolean {
  const accOk = accountabilities.every(
    (a) => a.status === "Approved" || a.status === "Closed",
  );
  const reimOk = reimbursements.every(
    (r) => r.status === "Reimbursed" || r.status === "Closed",
  );
  return accOk && reimOk;
}

// Compact status helper used by the UI to pick a tone / label.
export function accountabilityToneOf(s: AccountabilityStatus): "slate" | "amber" | "sky" | "emerald" | "rose" {
  switch (s) {
    case "Not Open":              return "slate";
    case "Open":                  return "amber";
    case "NetSuite ID Submitted": return "sky";
    case "Under Accountant Review": return "sky";
    case "Returned for Correction": return "rose";
    case "Approved":              return "emerald";
    case "Closed":                return "emerald";
  }
}

export function reimbursementToneOf(s: ReimbursementStatus): "slate" | "amber" | "sky" | "emerald" | "rose" {
  switch (s) {
    case "Draft":                       return "slate";
    case "Submitted":                   return "amber";
    case "Supervisor Review":           return "sky";
    case "Approved for Reimbursement":  return "sky";
    case "Returned for Correction":     return "rose";
    case "Queued for Accountant":       return "amber";
    case "Reimbursed":                  return "emerald";
    case "Closed":                      return "emerald";
  }
}

// ──────────────────────────────────────────────────────────────────────
// Aggregation helpers used by the dashboards
// ──────────────────────────────────────────────────────────────────────

export function computeStaffBalance(
  staffId: string,
  staffName: string,
  district: string,
  requests: WeeklyFundRequest[],
): StaffFundBalance {
  const open = requests.filter((r) =>
    ["DISBURSED", "RECEIVED", "IN_USE", "ACCOUNTABILITY_RETURNED"].includes(r.status),
  );
  const openDisbursed = open.reduce<Money>(
    (a, r) => moneyAdd(a, r.disbursedAmount ?? ZERO_UGX),
    ZERO_UGX,
  );
  const openAccounted = open.reduce<Money>(
    (a, r) => moneyAdd(a, r.accountedAmount ?? ZERO_UGX),
    ZERO_UGX,
  );
  const outstanding = moneySub(openDisbursed, openAccounted);
  const oldest = open
    .map((r) => r.period.weekStartIso)
    .sort()[0];

  const weeksOutstanding = open.length;
  const flagged = outstanding.amount > 0 && weeksOutstanding >= 2;

  return {
    staffId,
    staffName,
    district,
    openDisbursed,
    openAccounted,
    outstanding,
    weeksOutstanding,
    oldestWeekIso: oldest,
    flagged,
  };
}

export function priorWeekClosedFor(
  request: WeeklyFundRequest,
  allRequests: WeeklyFundRequest[],
): boolean {
  // W1 has no prior week — always cleared.
  if (request.period.weekOfMonth === 1) return true;
  const prior = allRequests.find(
    (r) =>
      r.staffId === request.staffId &&
      r.period.monthIso === request.period.monthIso &&
      r.period.weekOfMonth === ((request.period.weekOfMonth - 1) as WeekOfMonth),
  );
  if (!prior) return true; // no prior week request exists — treat as cleared
  return prior.status === "CLOSED";
}
