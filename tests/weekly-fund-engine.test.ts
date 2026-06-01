import { describe, it, expect } from "vitest";
import {
  isAllowedTransition,
  moneyAdd,
  moneySub,
  moneyGte,
  formatMoney,
  ZERO_UGX,
  calculateWeeklyFundRequestTotal,
  checkWeeklyFundRequestEligibility,
  confirmWeeklyFundRequest,
  approveWeeklyFundRequestByLead,
  returnWeeklyFundRequestByLead,
  disburseWeeklyFundRequest,
  confirmStaffReceipt,
  submitWeeklyFundAccountability,
  approveWeeklyFundAccountability,
  computeOverspendThreshold,
  OVERSPEND_HIGH_THRESHOLD_PCT,
  reconcileAccountability,
  resolveApprover,
  resolveReimbursementRoute,
  submitReimbursementClaim,
  computeRiskFlags,
  priorWeekClosedFor,
  postDisbursementGateOpen,
} from "@/lib/funds/weekly-fund-engine";
import type {
  Money,
  WeeklyFundRequest,
  WeeklyFundRequestActivity,
  WeeklyFundRequestStatus,
  FundAccountability,
  ReimbursementClaim,
} from "@/lib/funds/weekly-fund-types";

// ──────────────────────────── Fixtures ─────────────────────────────
//
// Pure-function tests, so the fixture is a JSON-shaped object with
// only the fields the engine actually reads. Anything an engine fn
// doesn't touch is omitted intentionally — adding it would only make
// the tests fragile to type expansion.

function ugx(amount: number): Money {
  return { amount, currency: "UGX" };
}

function makeActivity(over: Partial<WeeklyFundRequestActivity> = {}): WeeklyFundRequestActivity {
  return {
    id: "ACT-1",
    originPlanLineId: "PL-1",
    kind: "SchoolVisit",
    title: "School Visit · Test School",
    plannedDay: "Mon 13",
    costBreakdown: {
      transport: ugx(20_000),
      allowance: ugx(10_000),
      meals:     ugx(15_000),
      materials: ugx(0),
      misc:      ugx(0),
    },
    totalCost: ugx(45_000),
    status: "Planned",
    ...over,
  };
}

function makeRequest(
  over: Partial<WeeklyFundRequest> = {},
  status: WeeklyFundRequestStatus = "AUTO_GENERATED",
): WeeklyFundRequest {
  const activities = over.activities ?? [makeActivity()];
  const planned = activities.reduce<Money>((a, x) => moneyAdd(a, x.totalCost), ZERO_UGX);
  return {
    id: "WFR-2026-05-W2-STF-PC",
    staffId: "STF-1",
    staffName: "Paul Chinyama",
    staffRole: "CCEO",
    district: "Kampala",
    programLeadId: "PL-1",
    programLeadName: "Daniel Mwangi",
    countryId: "UG",
    monthlyPlanId: "MP-2026-05",
    period: {
      fyLabel: "FY 2026",
      quarter: "Q2",
      monthIso: "2026-05",
      monthLabel: "May 2026",
      weekOfMonth: 2,
      weekStartIso: "2026-05-09",
      weekEndIso: "2026-05-15",
    },
    status,
    plannedAmount: planned,
    requestedAmount: planned,
    activities,
    adjustments: [],
    flags: [],
    notes: "",
    source: "AUTO_FROM_PLAN",
    ...over,
  };
}

const STAFF = { id: "STF-1", name: "Paul" };
const LEAD = { id: "PL-1", name: "Daniel" };
const ACCT = { id: "ACC-1", name: "Moses" };

// ──────────────────────────── State machine ─────────────────────────

describe("isAllowedTransition", () => {
  it("permits the documented happy path end-to-end", () => {
    expect(isAllowedTransition("AUTO_GENERATED", "DRAFT")).toBe(true);
    expect(isAllowedTransition("DRAFT", "SUBMITTED")).toBe(true);
    expect(isAllowedTransition("SUBMITTED", "APPROVED")).toBe(true);
    expect(isAllowedTransition("APPROVED", "READY_TO_DISBURSE")).toBe(true);
    expect(isAllowedTransition("READY_TO_DISBURSE", "DISBURSED")).toBe(true);
    expect(isAllowedTransition("DISBURSED", "RECEIVED")).toBe(true);
    expect(isAllowedTransition("RECEIVED", "IN_USE")).toBe(true);
    expect(isAllowedTransition("IN_USE", "ACCOUNTABILITY_SUBMITTED")).toBe(true);
    expect(isAllowedTransition("ACCOUNTABILITY_SUBMITTED", "ACCOUNTABILITY_APPROVED")).toBe(true);
    expect(isAllowedTransition("ACCOUNTABILITY_APPROVED", "CLOSED")).toBe(true);
    expect(isAllowedTransition("CLOSED", "ARCHIVED")).toBe(true);
  });

  it("rejects the dangerous skips", () => {
    // Skipping approval entirely.
    expect(isAllowedTransition("SUBMITTED", "DISBURSED")).toBe(false);
    // Disbursing before READY_TO_DISBURSE / APPROVED.
    expect(isAllowedTransition("DRAFT", "DISBURSED")).toBe(false);
    // Re-opening closed work.
    expect(isAllowedTransition("ARCHIVED", "DRAFT")).toBe(false);
    expect(isAllowedTransition("CLOSED", "DRAFT")).toBe(false);
  });

  it("treats ARCHIVED as terminal — no outgoing transitions", () => {
    expect(isAllowedTransition("ARCHIVED", "CLOSED")).toBe(false);
    expect(isAllowedTransition("ARCHIVED", "ARCHIVED")).toBe(false);
  });
});

// ──────────────────────────── Money math ────────────────────────────

describe("money helpers", () => {
  it("adds and subtracts amounts of the same currency", () => {
    expect(moneyAdd(ugx(100), ugx(50))).toEqual(ugx(150));
    expect(moneySub(ugx(100), ugx(30))).toEqual(ugx(70));
  });

  it("throws on currency mismatch instead of silently coercing", () => {
    expect(() => moneyAdd(ugx(100), { amount: 50, currency: "USD" } as Money)).toThrow();
  });

  it("compares via moneyGte only with matching currency", () => {
    expect(moneyGte(ugx(100), ugx(50))).toBe(true);
    expect(moneyGte(ugx(50), ugx(100))).toBe(false);
    expect(moneyGte(ugx(100), { amount: 50, currency: "USD" } as Money)).toBe(false);
  });

  it("formats UGX with B/M/K suffixes", () => {
    expect(formatMoney(ugx(1_500_000_000))).toBe("UGX 1.50B");
    expect(formatMoney(ugx(2_300_000))).toBe("UGX 2.30M");
    expect(formatMoney(ugx(1_200))).toBe("UGX 1K");
    expect(formatMoney(ugx(500))).toBe("UGX 500");
  });
});

// ──────────────────────────── Totals & eligibility ──────────────────

describe("calculateWeeklyFundRequestTotal", () => {
  it("sums non-cancelled activities only", () => {
    const total = calculateWeeklyFundRequestTotal({
      activities: [
        makeActivity({ id: "A", totalCost: ugx(10_000) }),
        makeActivity({ id: "B", totalCost: ugx(20_000) }),
        makeActivity({ id: "C", totalCost: ugx(50_000), status: "Cancelled" }),
      ],
    });
    expect(total).toEqual(ugx(30_000));
  });

  it("returns zero on an empty request", () => {
    expect(calculateWeeklyFundRequestTotal({ activities: [] })).toEqual(ZERO_UGX);
  });
});

describe("checkWeeklyFundRequestEligibility", () => {
  it("returns no blockers when everything is in order", () => {
    const req = makeRequest({}, "SUBMITTED");
    const blockers = checkWeeklyFundRequestEligibility(req, {
      priorWeekClosed: true,
      fundsAvailableAtCountry: ugx(1_000_000),
      planActivityIds: new Set(["PL-1"]),
      costTolerancePct: 10,
    });
    expect(blockers).toEqual([]);
  });

  it("flags PRIOR_WEEK_NOT_CLOSED when the prior accountability is open", () => {
    const req = makeRequest({}, "SUBMITTED");
    const blockers = checkWeeklyFundRequestEligibility(req, {
      priorWeekClosed: false,
      fundsAvailableAtCountry: ugx(1_000_000),
      planActivityIds: new Set(["PL-1"]),
      costTolerancePct: 10,
    });
    expect(blockers).toContain("PRIOR_WEEK_NOT_CLOSED");
  });

  it("flags FUNDS_NOT_RECEIVED when country balance is below requested", () => {
    const req = makeRequest({}, "SUBMITTED");
    const blockers = checkWeeklyFundRequestEligibility(req, {
      priorWeekClosed: true,
      fundsAvailableAtCountry: ugx(1_000),
      planActivityIds: new Set(["PL-1"]),
      costTolerancePct: 10,
    });
    expect(blockers).toContain("FUNDS_NOT_RECEIVED_AT_COUNTRY");
  });

  it("flags OVER_PLAN_TOLERANCE when requested exceeds planned by more than allowed pct", () => {
    const req = makeRequest({ requestedAmount: ugx(60_000), plannedAmount: ugx(45_000) }, "SUBMITTED");
    // delta = 15,000 / 45,000 = 33% > 10% tolerance
    const blockers = checkWeeklyFundRequestEligibility(req, {
      priorWeekClosed: true,
      fundsAvailableAtCountry: ugx(1_000_000),
      planActivityIds: new Set(["PL-1"]),
      costTolerancePct: 10,
    });
    expect(blockers).toContain("OVER_PLAN_TOLERANCE");
  });

  it("flags ACTIVITY_NOT_ON_APPROVED_PLAN when an activity has no plan match", () => {
    const req = makeRequest({
      activities: [makeActivity({ originPlanLineId: "PL-UNKNOWN" })],
    }, "SUBMITTED");
    const blockers = checkWeeklyFundRequestEligibility(req, {
      priorWeekClosed: true,
      fundsAvailableAtCountry: ugx(1_000_000),
      planActivityIds: new Set(["PL-1"]),
      costTolerancePct: 10,
    });
    expect(blockers).toContain("ACTIVITY_NOT_ON_APPROVED_PLAN");
  });
});

// ──────────────────────────── Transition functions ──────────────────

describe("confirmWeeklyFundRequest", () => {
  it("transitions DRAFT → SUBMITTED, stamps submittedAt, writes audit + lead notification", () => {
    const req = makeRequest({}, "DRAFT");
    const r = confirmWeeklyFundRequest(req, STAFF, { note: "ready to go" });
    expect(r.ok).toBe(true);
    expect(r.data?.status).toBe("SUBMITTED");
    expect(r.data?.submittedAt).toBeDefined();
    expect(r.audit).toHaveLength(1);
    expect(r.audit[0].action).toBe("SUBMITTED");
    expect(r.notifications.some((n) => n.audienceRole === "ProgramLead")).toBe(true);
  });

  it("refuses to submit from a non-Draft status", () => {
    const req = makeRequest({}, "APPROVED");
    const r = confirmWeeklyFundRequest(req, STAFF);
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/Cannot submit/);
  });
});

describe("approveWeeklyFundRequestByLead", () => {
  it("transitions SUBMITTED → APPROVED with lead stamp + accountant notification", () => {
    const req = makeRequest({}, "SUBMITTED");
    const r = approveWeeklyFundRequestByLead(req, LEAD);
    expect(r.ok).toBe(true);
    expect(r.data?.status).toBe("APPROVED");
    expect(r.data?.approvedByLeadId).toBe(LEAD.id);
    expect(r.notifications.some((n) => n.audienceRole === "Accountant")).toBe(true);
  });
});

describe("returnWeeklyFundRequestByLead", () => {
  it("requires a meaningful reason (min 5 chars)", () => {
    const req = makeRequest({}, "SUBMITTED");
    expect(returnWeeklyFundRequestByLead(req, LEAD, "no").ok).toBe(false);
  });

  it("returns SUBMITTED → RETURNED_TO_STAFF with the reason in audit", () => {
    const req = makeRequest({}, "SUBMITTED");
    const r = returnWeeklyFundRequestByLead(req, LEAD, "Please add receipts");
    expect(r.ok).toBe(true);
    expect(r.data?.status).toBe("RETURNED_TO_STAFF");
    expect(r.audit[0].note).toBe("Please add receipts");
  });
});

// ──────────────────────────── Disbursement gates ────────────────────

describe("disburseWeeklyFundRequest", () => {
  const base = makeRequest({}, "APPROVED");
  const ctx = {
    method: "Cash" as const,
    reference: "TXN-001",
    fundsReceivedId: "FR-1",
    accountant: ACCT,
    fundsAvailable: ugx(1_000_000),
    priorWeekClosed: true,
  };

  it("disburses on a green-path APPROVED request", () => {
    const r = disburseWeeklyFundRequest(base, { amount: ugx(45_000), ...ctx });
    expect(r.ok).toBe(true);
    expect(r.data?.request.status).toBe("DISBURSED");
    expect(r.data?.disbursement.amount).toEqual(ugx(45_000));
    expect(r.notifications.some((n) => n.audienceRole === "Staff")).toBe(true);
  });

  it("refuses to disburse more than the requested amount", () => {
    const r = disburseWeeklyFundRequest(base, { amount: ugx(100_000), ...ctx });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/exceeds requested/);
  });

  it("refuses to disburse more than the funds-received batch can cover", () => {
    const r = disburseWeeklyFundRequest(base, {
      amount: ugx(45_000),
      ...ctx,
      fundsAvailable: ugx(1_000),
    });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/Insufficient funds/);
  });

  it("blocks disbursement when prior week is not closed and no override is provided", () => {
    const r = disburseWeeklyFundRequest(base, {
      amount: ugx(45_000),
      ...ctx,
      priorWeekClosed: false,
    });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/Prior week/);
  });

  it("permits disbursement with prior-week override, but writes the override to audit", () => {
    const r = disburseWeeklyFundRequest(base, {
      amount: ugx(45_000),
      ...ctx,
      priorWeekClosed: false,
      overrideAccountabilityGate: { reason: "Approved by CD verbally" },
    });
    expect(r.ok).toBe(true);
    expect(r.audit.some((a) => a.action === "OVERRIDE")).toBe(true);
  });

  it("refuses to disburse from RECEIVED / IN_USE / CLOSED", () => {
    for (const status of ["RECEIVED", "IN_USE", "CLOSED"] as const) {
      const r = disburseWeeklyFundRequest(makeRequest({}, status), {
        amount: ugx(45_000),
        ...ctx,
      });
      expect(r.ok).toBe(false);
    }
  });
});

// ──────────────────────────── Accountability ────────────────────────

describe("submitWeeklyFundAccountability", () => {
  it("requires accounted + returned to equal disbursed (or fail clearly)", () => {
    const req = makeRequest(
      { disbursedAmount: ugx(45_000) },
      "RECEIVED",
    );
    const r = submitWeeklyFundAccountability(req, STAFF, {
      accountedAmount: ugx(40_000),
      returnedAmount:  ugx(0), // 40 ≠ 45
      receipts: [{ activityId: "ACT-1", receiptRef: "RC-1", amount: ugx(40_000) }],
    });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/must equal disbursed/);
  });

  it("requires at least one receipt", () => {
    const req = makeRequest({ disbursedAmount: ugx(45_000) }, "RECEIVED");
    const r = submitWeeklyFundAccountability(req, STAFF, {
      accountedAmount: ugx(45_000),
      returnedAmount:  ugx(0),
      receipts: [],
    });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/receipt/);
  });

  it("accepts a balanced submission with at least one receipt", () => {
    const req = makeRequest({ disbursedAmount: ugx(45_000) }, "RECEIVED");
    const r = submitWeeklyFundAccountability(req, STAFF, {
      accountedAmount: ugx(40_000),
      returnedAmount:  ugx(5_000),
      receipts: [{ activityId: "ACT-1", receiptRef: "RC-1", amount: ugx(40_000) }],
    });
    expect(r.ok).toBe(true);
    expect(r.data?.status).toBe("ACCOUNTABILITY_SUBMITTED");
  });

  it("auto-closes the request when the lead approves the accountability", () => {
    const req = makeRequest({}, "ACCOUNTABILITY_SUBMITTED");
    const r = approveWeeklyFundAccountability(req, LEAD);
    expect(r.ok).toBe(true);
    expect(r.data?.status).toBe("CLOSED");
    expect(r.audit.map((a) => a.action)).toContain("CLOSED");
  });
});

// ──────────────────────────── Reconciliation ────────────────────────

describe("computeOverspendThreshold", () => {
  it("returns Normal when spent ≤ advanced", () => {
    expect(computeOverspendThreshold(100, 100).flag).toBe("Normal");
    expect(computeOverspendThreshold(100, 80).flag).toBe("Normal");
  });

  it(`flags RequiresCDReview when overspend > ${OVERSPEND_HIGH_THRESHOLD_PCT}%`, () => {
    // 100 advanced, 120 spent → 20% over → escalates.
    const r = computeOverspendThreshold(100, 120);
    expect(r.flag).toBe("RequiresCDReview");
    expect(r.pct).toBeCloseTo(20);
  });

  it(`keeps Normal at the boundary (≤ ${OVERSPEND_HIGH_THRESHOLD_PCT}%)`, () => {
    const r = computeOverspendThreshold(100, 115); // exactly 15%
    expect(r.flag).toBe("Normal");
  });
});

describe("reconcileAccountability", () => {
  const base = {
    fundRequestId: "WFR-1",
    disbursementId: "DSB-1",
    staffId: STAFF.id,
    staffName: STAFF.name,
    staffRole: "CCEO" as const,
    netsuiteExpenseId: "4001",
    advancedAmountUgx: 100_000,
  };

  it("returns Fully Accounted when spent equals advanced", () => {
    const r = reconcileAccountability({ ...base, amountSpentUgx: 100_000 });
    expect(r.ok).toBe(true);
    expect(r.data?.reconciliation.outcome).toBe("Fully Accounted");
    expect(r.data?.balanceReturn).toBeUndefined();
    expect(r.data?.autoReimbursement).toBeUndefined();
  });

  it("creates a BalanceReturn when underspent", () => {
    const r = reconcileAccountability({ ...base, amountSpentUgx: 60_000 });
    expect(r.ok).toBe(true);
    expect(r.data?.reconciliation.outcome).toBe("Balance To Return");
    expect(r.data?.reconciliation.balanceToReturnUgx).toBe(40_000);
    expect(r.data?.balanceReturn).toBeDefined();
    expect(r.data?.balanceReturn?.amountUgx).toBe(40_000);
  });

  it("creates an auto Reimbursement when overspent — and requires a reason", () => {
    const missing = reconcileAccountability({ ...base, amountSpentUgx: 130_000 });
    expect(missing.ok).toBe(false);
    expect(missing.error).toMatch(/Overspend reason/);

    const r = reconcileAccountability({
      ...base,
      amountSpentUgx: 130_000,
      overspendReason: "TransportCostIncreased",
    });
    expect(r.ok).toBe(true);
    expect(r.data?.reconciliation.outcome).toBe("Reimbursement Due");
    expect(r.data?.autoReimbursement?.amountToReimburseUgx).toBe(30_000);
  });

  it("routes high-overspend CCEO claims directly to the Country Director (15% rule)", () => {
    const r = reconcileAccountability({
      ...base,
      amountSpentUgx: 130_000, // 30% over → above 15% threshold
      overspendReason: "TransportCostIncreased",
    });
    expect(r.data?.autoReimbursement?.approvalRoute).toBe("CountryDirector");
    expect(r.data?.autoReimbursement?.thresholdFlag).toBe("RequiresCDReview");
  });

  it("keeps low-overspend CCEO claims on the Program Lead route", () => {
    const r = reconcileAccountability({
      ...base,
      amountSpentUgx: 110_000, // 10% over → within threshold
      overspendReason: "TransportCostIncreased",
    });
    expect(r.data?.autoReimbursement?.approvalRoute).toBe("ProgramLead");
  });

  it("rejects malformed NetSuite Expense IDs", () => {
    const r = reconcileAccountability({
      ...base,
      netsuiteExpenseId: "wrong-format-123",
      amountSpentUgx: 100_000,
    });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/NetSuite Expense ID/);
  });
});

// ──────────────────────────── Routing ───────────────────────────────

describe("resolveApprover", () => {
  it("routes CCEO requests to the Program Lead", () => {
    expect(resolveApprover("CCEO")).toBe("ProgramLead");
  });

  it("routes everyone else straight to the Country Director", () => {
    for (const role of ["ProgramLead", "ProgramAccountant", "ImpactAssessment", "SpecialProjectsCoordinator", "Admin"] as const) {
      expect(resolveApprover(role)).toBe("CountryDirector");
    }
  });
});

describe("resolveReimbursementRoute", () => {
  it("routes CCEO claims to PL first; everyone else straight to CD", () => {
    expect(resolveReimbursementRoute("CCEO")).toBe("ProgramLead");
    expect(resolveReimbursementRoute("ProgramLead")).toBe("CountryDirector");
    expect(resolveReimbursementRoute("ImpactAssessment")).toBe("CountryDirector");
  });
});

describe("submitReimbursementClaim", () => {
  const valid = {
    staffId: STAFF.id,
    staffName: STAFF.name,
    staffRole: "CCEO" as const,
    amountSpentUgx: 80_000,
    amountPreviouslyDisbursedUgx: 50_000,
    reasonPersonalFundsUsed: "Vendor wouldn't take mobile money",
    netsuiteExpenseId: "9999",
  };

  it("accepts a valid claim and computes the difference", () => {
    const r = submitReimbursementClaim(valid);
    expect(r.ok).toBe(true);
    expect(r.data?.amountToReimburseUgx).toBe(30_000);
    expect(r.data?.approvalRoute).toBe("ProgramLead"); // CCEO routes via PL
  });

  it("rejects when previously-disbursed already covers the spend", () => {
    const r = submitReimbursementClaim({ ...valid, amountSpentUgx: 40_000 });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/Nothing to reimburse/);
  });

  it("requires a non-trivial reason", () => {
    const r = submitReimbursementClaim({ ...valid, reasonPersonalFundsUsed: "x" });
    expect(r.ok).toBe(false);
  });
});

// ──────────────────────────── Risk + prior-week ─────────────────────

describe("computeRiskFlags", () => {
  it("flags MissingSalesforceIds + PreviousAccountabilityPending based on context", () => {
    const flags = computeRiskFlags(makeRequest({}, "APPROVED"), {
      priorWeekClosed: false,
      priorWeekMissingReceipts: true,
      priorWeekMissingSalesforceIds: true,
      staffOnLeave: false,
    });
    expect(flags).toEqual(expect.arrayContaining(["PreviousAccountabilityPending", "MissingSalesforceIds"]));
  });

  it("flags ExceedsApprovedWeeklyPlan when requested > planned by >10%", () => {
    const req = makeRequest({ plannedAmount: ugx(100_000), requestedAmount: ugx(120_000) }, "APPROVED");
    const flags = computeRiskFlags(req, {
      priorWeekClosed: true,
      priorWeekMissingReceipts: false,
      priorWeekMissingSalesforceIds: false,
      staffOnLeave: false,
    });
    expect(flags).toContain("ExceedsApprovedWeeklyPlan");
  });

  it("flags HighTransportVariance when transport > 35% of total", () => {
    const heavyTransport = makeActivity({
      id: "X",
      costBreakdown: {
        transport: ugx(50_000),
        allowance: ugx(10_000),
        meals:     ugx(10_000),
        materials: ugx(10_000),
        misc:      ugx(10_000),
      },
      totalCost: ugx(90_000),
    });
    const req = makeRequest({
      activities: [heavyTransport],
      plannedAmount: ugx(90_000),
      requestedAmount: ugx(90_000),
    }, "APPROVED");
    const flags = computeRiskFlags(req, {
      priorWeekClosed: true,
      priorWeekMissingReceipts: false,
      priorWeekMissingSalesforceIds: false,
      staffOnLeave: false,
    });
    expect(flags).toContain("HighTransportVariance");
  });
});

describe("priorWeekClosedFor", () => {
  it("treats W1 as cleared with no prior", () => {
    const w1 = makeRequest({
      id: "WFR-W1",
      period: { ...makeRequest().period, weekOfMonth: 1 },
    });
    expect(priorWeekClosedFor(w1, [w1])).toBe(true);
  });

  it("treats W2 as cleared when W1 is CLOSED", () => {
    const w1 = makeRequest(
      { id: "WFR-W1", period: { ...makeRequest().period, weekOfMonth: 1 } },
      "CLOSED",
    );
    const w2 = makeRequest({ id: "WFR-W2" });
    expect(priorWeekClosedFor(w2, [w1, w2])).toBe(true);
  });

  it("treats W2 as NOT cleared when W1 is still in flight", () => {
    const w1 = makeRequest(
      { id: "WFR-W1", period: { ...makeRequest().period, weekOfMonth: 1 } },
      "DISBURSED",
    );
    const w2 = makeRequest({ id: "WFR-W2" });
    expect(priorWeekClosedFor(w2, [w1, w2])).toBe(false);
  });

  it("treats W2 as cleared when there's no W1 request at all", () => {
    const w2 = makeRequest({ id: "WFR-W2" });
    expect(priorWeekClosedFor(w2, [w2])).toBe(true);
  });
});

// ──────────────────────────── Post-disbursement gate ────────────────

describe("postDisbursementGateOpen", () => {
  function acc(status: FundAccountability["status"]): FundAccountability {
    return {
      id: `AC-${status}`,
      fundRequestId: "WFR-1",
      disbursementId: "DSB-1",
      staffId: STAFF.id,
      staffName: STAFF.name,
      amountDisbursedUgx: 50_000,
      status,
    } as FundAccountability;
  }

  function reim(status: ReimbursementClaim["status"]): ReimbursementClaim {
    return {
      id: `REIM-${status}`,
      staffId: STAFF.id,
      staffName: STAFF.name,
      staffRole: "CCEO",
      amountSpentUgx: 40_000,
      amountPreviouslyDisbursedUgx: 30_000,
      amountToReimburseUgx: 10_000,
      reasonPersonalFundsUsed: "n/a",
      netsuiteExpenseId: "5001",
      approvalRoute: "ProgramLead",
      status,
    } as ReimbursementClaim;
  }

  it("opens the gate when everything prior is Approved/Closed/Reimbursed", () => {
    expect(
      postDisbursementGateOpen([acc("Approved")], [reim("Reimbursed")]),
    ).toBe(true);
  });

  it("closes the gate if any accountability is still open", () => {
    expect(
      postDisbursementGateOpen([acc("Open")], [reim("Reimbursed")]),
    ).toBe(false);
  });

  it("closes the gate if any reimbursement is unfinished", () => {
    expect(
      postDisbursementGateOpen([acc("Approved")], [reim("Submitted")]),
    ).toBe(false);
  });
});

// ──────────────────────────── Happy-path integration ────────────────
//
// Runs the actual lifecycle from auto-generated through CLOSED, threading
// the engine result of each step into the next. If anything in the
// chain rejects a valid transition or loses state, this test will fail
// long before integration QA notices.

describe("happy-path lifecycle", () => {
  it("flows AUTO_GENERATED → CLOSED through every documented stage", () => {
    let req = makeRequest({}, "DRAFT");

    const submitted = confirmWeeklyFundRequest(req, STAFF);
    expect(submitted.ok).toBe(true);
    req = submitted.data!;

    const approved = approveWeeklyFundRequestByLead(req, LEAD);
    expect(approved.ok).toBe(true);
    req = approved.data!;

    const disbursed = disburseWeeklyFundRequest(req, {
      amount: ugx(45_000),
      method: "Cash",
      reference: "TXN-001",
      fundsReceivedId: "FR-1",
      fundsAvailable: ugx(1_000_000),
      accountant: ACCT,
      priorWeekClosed: true,
    });
    expect(disbursed.ok).toBe(true);
    req = disbursed.data!.request;

    const received = confirmStaffReceipt(req, disbursed.data!.disbursement, STAFF);
    expect(received.ok).toBe(true);
    req = received.data!.request;
    // RECEIVED → IN_USE is implicit in real life (staff starts spending);
    // we hand-advance here because there's no engine fn for that step.
    req = { ...req, status: "IN_USE" };

    const accounted = submitWeeklyFundAccountability(req, STAFF, {
      accountedAmount: ugx(45_000),
      returnedAmount:  ugx(0),
      receipts: [{ activityId: "ACT-1", receiptRef: "RC-1", amount: ugx(45_000) }],
    });
    expect(accounted.ok).toBe(true);
    req = accounted.data!;

    const closed = approveWeeklyFundAccountability(req, LEAD);
    expect(closed.ok).toBe(true);
    expect(closed.data?.status).toBe("CLOSED");
  });
});
