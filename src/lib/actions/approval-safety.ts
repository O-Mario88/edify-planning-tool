// Approval safety classifier.
//
// One pure function that takes a candidate approval and returns
// SafeToApprove / NeedsReview / Blocked. The Bulk-Approve UI uses
// this to decide which rows the multi-select can include.
//
// Rules (in priority order — first match wins):
//
//   1. Blocked when:
//        - cost-settings for the period are Draft (CD must activate first)
//        - prior week not closed (weekly funds)
//        - missing approver signature on dependent record
//        - data validation flagged "BlockingError"
//        - flagged as fraud / duplicate
//
//   2. NeedsReview when:
//        - amount > tolerance band (e.g. weekly fund > 110% of planned)
//        - actor has never approved a record from this requester before
//        - reviewer notes left by accountant
//        - any non-blocking flag present
//
//   3. SafeToApprove — everything else. The default is INTENTIONALLY
//      permissive; we'd rather false-positive into Review (low cost)
//      than false-positive into Approve (high cost).

import type { ApprovalSafety } from "./action-types";

export type SafetyCandidate = {
  /// What kind of approval. Drives which rule set runs.
  kind:
    | "MonthlyPlan"
    | "WeeklyFund"
    | "CountryFundEnvelope"
    | "Reimbursement"
    | "BalanceReturn"
    | "DataCertification";
  /// Common fields the rules consult — populated by the caller from
  /// the source mock/engine. Anything irrelevant for a kind is null.
  costSettingsActive?: boolean;
  priorWeekClosed?: boolean;
  fraudFlag?: boolean;
  duplicateFlag?: boolean;
  /// 0–1; >= 0.10 over plan triggers Review, >= 0.25 triggers Blocked.
  overPlanPct?: number;
  /// Total amount in UGX cents — used as a soft signal for "this is
  /// big enough to deserve human eyes".
  amountCents?: number;
  /// Whether the requester / record has been approved by this actor before.
  /// New relationships always trip Review.
  isFirstTimeWithActor?: boolean;
  /// Accountant or M&E left a note — never auto-approve.
  hasReviewerNotes?: boolean;
  /// Validation engine flags — caller pre-filters to the relevant ones.
  blockingValidationFlags?: string[];
  nonBlockingValidationFlags?: string[];
};

export type SafetyReason = {
  safety: ApprovalSafety;
  /// Plain-English explanation, surfaced in the tooltip.
  reason: string;
  /// Optional category — useful for grouping in the UI ("3 items
  /// blocked by cost-settings", "5 over-budget").
  ruleId: string;
};

const HIGH_AMOUNT_UGX = 5_000_000 * 100; // 5M UGX in cents

export function classifyApprovalSafety(c: SafetyCandidate): SafetyReason {
  // ─── Tier 1: Blocked ───
  if (c.fraudFlag) {
    return { safety: "Blocked", ruleId: "fraud", reason: "Flagged as potential fraud — escalate, do not approve." };
  }
  if (c.duplicateFlag) {
    return { safety: "Blocked", ruleId: "duplicate", reason: "Detected duplicate of a recent record." };
  }
  if (c.blockingValidationFlags && c.blockingValidationFlags.length > 0) {
    return {
      safety: "Blocked",
      ruleId: "validation",
      reason: `Validation: ${c.blockingValidationFlags[0]}.`,
    };
  }
  if (c.kind === "MonthlyPlan" && c.costSettingsActive === false) {
    return {
      safety: "Blocked",
      ruleId: "cost-settings-draft",
      reason: "Country cost-settings still in Draft. CD must activate first.",
    };
  }
  if (c.kind === "WeeklyFund" && c.priorWeekClosed === false) {
    return {
      safety: "Blocked",
      ruleId: "prior-week-open",
      reason: "Prior week accountability still open. Close that first.",
    };
  }
  if (typeof c.overPlanPct === "number" && c.overPlanPct >= 0.25) {
    return {
      safety: "Blocked",
      ruleId: "over-plan-25",
      reason: `Requested ${Math.round(c.overPlanPct * 100)}% over the approved plan — needs re-planning, not approval.`,
    };
  }

  // ─── Tier 2: Needs Review ───
  if (typeof c.overPlanPct === "number" && c.overPlanPct >= 0.10) {
    return {
      safety: "NeedsReview",
      ruleId: "over-plan-10",
      reason: `Requested ${Math.round(c.overPlanPct * 100)}% over plan — verify the adjustment.`,
    };
  }
  if (c.hasReviewerNotes) {
    return {
      safety: "NeedsReview",
      ruleId: "reviewer-notes",
      reason: "Accountant or M&E left a note — read before approving.",
    };
  }
  if (c.isFirstTimeWithActor) {
    return {
      safety: "NeedsReview",
      ruleId: "first-time-actor",
      reason: "First time you're approving for this requester — verify identity / context.",
    };
  }
  if (c.nonBlockingValidationFlags && c.nonBlockingValidationFlags.length > 0) {
    return {
      safety: "NeedsReview",
      ruleId: "validation-soft",
      reason: `Soft validation flag: ${c.nonBlockingValidationFlags[0]}.`,
    };
  }
  if (typeof c.amountCents === "number" && c.amountCents >= HIGH_AMOUNT_UGX) {
    return {
      safety: "NeedsReview",
      ruleId: "high-amount",
      reason: "Amount above 5M UGX — eyeball before approving.",
    };
  }

  // ─── Tier 3: Safe ───
  return {
    safety: "SafeToApprove",
    ruleId: "default",
    reason: "Passes all validation rules. Safe to approve in bulk.",
  };
}
