import { describe, it, expect } from "vitest";
import { countsTowardTarget, isFieldComplete } from "@/lib/target-counting";

// The "what counts" rule is the load-bearing distinction between
// performance-management math and progress signals. Drift here means a
// CCEO who logs 100 activities but has 0 verified looks "On Track" on
// one card and "Critical" on another. This file pins the rule.

describe("countsTowardTarget", () => {
  it("counts Verified activities", () => {
    expect(countsTowardTarget({ status: "Verified" })).toBe(true);
  });

  it.each([
    "Planned",
    "Ready",
    "In Progress",
    "Submitted for Verification",
    "Salesforce ID Pending",
    "Completed",
    "Returned",
    "Overdue",
  ] as const)("does NOT count %s activities", (status) => {
    expect(countsTowardTarget({ status })).toBe(false);
  });
});

describe("isFieldComplete", () => {
  it.each([
    "Verified",
    "Submitted for Verification",
    "Salesforce ID Pending",
    "Completed",
  ] as const)("treats %s as field-complete", (status) => {
    expect(isFieldComplete({ status })).toBe(true);
  });

  it.each(["Planned", "Ready", "In Progress", "Returned", "Overdue"] as const)(
    "does NOT treat %s as field-complete",
    (status) => {
      expect(isFieldComplete({ status })).toBe(false);
    },
  );
});

describe("countsTowardTarget vs isFieldComplete contract", () => {
  // Critical invariant: every target-counting activity is also
  // field-complete. The converse must NOT hold (otherwise the two
  // helpers are redundant).
  const ALL_STATUSES = [
    "Verified",
    "Planned",
    "Ready",
    "In Progress",
    "Submitted for Verification",
    "Salesforce ID Pending",
    "Completed",
    "Returned",
    "Overdue",
  ] as const;

  it("verified ⊆ field-complete", () => {
    for (const status of ALL_STATUSES) {
      if (countsTowardTarget({ status })) {
        expect(isFieldComplete({ status })).toBe(true);
      }
    }
  });

  it("field-complete is strictly broader than target-counting", () => {
    const fieldComplete = ALL_STATUSES.filter((s) => isFieldComplete({ status: s }));
    const targetCounting = ALL_STATUSES.filter((s) => countsTowardTarget({ status: s }));
    expect(fieldComplete.length).toBeGreaterThan(targetCounting.length);
  });
});
