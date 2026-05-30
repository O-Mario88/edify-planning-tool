import { describe, it, expect } from "vitest";
import { classifyApprovalSafety } from "@/lib/actions/approval-safety";

// Approval safety is the bulk-approve safety net. These tests pin
// the rules verbatim — every "Blocked" should be a real reason, every
// "SafeToApprove" should actually be safe.

describe("classifyApprovalSafety — Blocked tier", () => {
  it("flags fraud highest priority", () => {
    const r = classifyApprovalSafety({ kind: "WeeklyFund", fraudFlag: true });
    expect(r.safety).toBe("Blocked");
    expect(r.ruleId).toBe("fraud");
  });

  it("flags duplicates", () => {
    const r = classifyApprovalSafety({ kind: "WeeklyFund", duplicateFlag: true });
    expect(r.safety).toBe("Blocked");
    expect(r.ruleId).toBe("duplicate");
  });

  it("treats blocking validation flags as blocking", () => {
    const r = classifyApprovalSafety({
      kind: "MonthlyPlan",
      blockingValidationFlags: ["Missing Receipts"],
    });
    expect(r.safety).toBe("Blocked");
    expect(r.reason).toMatch(/Missing Receipts/);
  });

  it("blocks a monthly plan when cost-settings are still Draft", () => {
    expect(classifyApprovalSafety({
      kind: "MonthlyPlan",
      costSettingsActive: false,
    }).safety).toBe("Blocked");
  });

  it("blocks a weekly fund when prior week is still open", () => {
    expect(classifyApprovalSafety({
      kind: "WeeklyFund",
      priorWeekClosed: false,
    }).safety).toBe("Blocked");
  });

  it("blocks anything ≥25% over plan", () => {
    expect(classifyApprovalSafety({ kind: "WeeklyFund", overPlanPct: 0.30 }).safety)
      .toBe("Blocked");
  });
});

describe("classifyApprovalSafety — NeedsReview tier", () => {
  it("requests review for 10–24% over plan", () => {
    expect(classifyApprovalSafety({ kind: "WeeklyFund", overPlanPct: 0.15 }).safety)
      .toBe("NeedsReview");
  });

  it("requests review when reviewer notes exist", () => {
    expect(classifyApprovalSafety({ kind: "WeeklyFund", hasReviewerNotes: true }).safety)
      .toBe("NeedsReview");
  });

  it("requests review for a first-time relationship", () => {
    expect(classifyApprovalSafety({
      kind: "MonthlyPlan",
      costSettingsActive: true,
      isFirstTimeWithActor: true,
    }).safety).toBe("NeedsReview");
  });

  it("treats high-amount payments as review-worthy", () => {
    expect(classifyApprovalSafety({
      kind: "WeeklyFund",
      priorWeekClosed: true,
      amountCents: 6_000_000 * 100, // 6M UGX
    }).safety).toBe("NeedsReview");
  });
});

describe("classifyApprovalSafety — SafeToApprove default", () => {
  it("returns Safe for a clean monthly plan", () => {
    const r = classifyApprovalSafety({
      kind: "MonthlyPlan",
      costSettingsActive: true,
      isFirstTimeWithActor: false,
      hasReviewerNotes: false,
    });
    expect(r.safety).toBe("SafeToApprove");
  });

  it("returns Safe for a clean weekly fund", () => {
    const r = classifyApprovalSafety({
      kind: "WeeklyFund",
      priorWeekClosed: true,
      overPlanPct: 0.05,
      amountCents: 1_000_000 * 100,
    });
    expect(r.safety).toBe("SafeToApprove");
  });
});
