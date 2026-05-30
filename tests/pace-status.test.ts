import { describe, it, expect } from "vitest";
import { getPaceStatus } from "@/lib/pace-status";

// pace-status is the single source of truth for how the same staff
// member's pace renders across My Targets, Team Targets, Leaderboard,
// Coverage. If these tests fail, the entire performance-management
// surface of the app silently disagrees with itself.
//
// Boundary cases that matter:
//   • ratio >= 0.95           → On Track
//   • 0.80 <= ratio < 0.95    → Needs Attention
//   • ratio < 0.80            → Critical
//   • each protected day grants `5 / target` of headroom
//   • adjustedRatio is clamped to 1.5 — wildly over-pace doesn't break

describe("getPaceStatus", () => {
  describe("base bands", () => {
    it("returns On Track at exactly the 95% boundary", () => {
      expect(getPaceStatus({ completed: 95, target: 100, expectedByNow: 100 })).toBe("On Track");
    });

    it("returns On Track when over-pacing", () => {
      expect(getPaceStatus({ completed: 120, target: 100, expectedByNow: 100 })).toBe("On Track");
    });

    it("returns Needs Attention just under the On Track cutoff", () => {
      expect(getPaceStatus({ completed: 94, target: 100, expectedByNow: 100 })).toBe("Needs Attention");
    });

    it("returns Needs Attention at the 80% floor", () => {
      expect(getPaceStatus({ completed: 80, target: 100, expectedByNow: 100 })).toBe("Needs Attention");
    });

    it("returns Critical just under the Needs Attention floor", () => {
      expect(getPaceStatus({ completed: 79, target: 100, expectedByNow: 100 })).toBe("Critical");
    });

    it("returns Critical at zero completion", () => {
      expect(getPaceStatus({ completed: 0, target: 100, expectedByNow: 100 })).toBe("Critical");
    });
  });

  describe("fairness adjustment for protected days", () => {
    // Tolerance formula: protectedDays * 5 / max(1, target)
    // So with target=100, 1 protected day = +0.05 to the ratio.

    it("nudges a Needs Attention case to On Track when enough leave covers the gap", () => {
      // 80/100 = 0.80 ratio. With 3 leave days → +0.15 = 0.95 → On Track.
      const base = getPaceStatus({ completed: 80, target: 100, expectedByNow: 100 });
      const adjusted = getPaceStatus({ completed: 80, target: 100, expectedByNow: 100, leaveDays: 3 });
      expect(base).toBe("Needs Attention");
      expect(adjusted).toBe("On Track");
    });

    it("treats leave, public holidays, and blocked days additively", () => {
      // 70/100 = 0.70 ratio. Each protected day = +0.05.
      // 2 leave + 2 holidays + 1 blocked = 5 days = +0.25 → 0.95 → On Track.
      expect(
        getPaceStatus({
          completed: 70,
          target: 100,
          expectedByNow: 100,
          leaveDays: 2,
          publicHolidays: 2,
          blockedDays: 1,
        }),
      ).toBe("On Track");
    });

    it("does not let protected days mask catastrophic underperformance", () => {
      // 10/100 = 0.10. With 5 protected days (+0.25) → 0.35 → still Critical.
      expect(
        getPaceStatus({ completed: 10, target: 100, expectedByNow: 100, leaveDays: 5 }),
      ).toBe("Critical");
    });

    it("clamps adjusted ratio at 1.5 so absurd protected counts don't break", () => {
      // 100/100 with 100 leave days. Without clamp: 1.0 + 5.0 = 6.0.
      // Should still resolve cleanly to On Track.
      expect(
        getPaceStatus({ completed: 100, target: 100, expectedByNow: 100, leaveDays: 100 }),
      ).toBe("On Track");
    });
  });

  describe("edge inputs", () => {
    it("handles expectedByNow of 0 without dividing by zero", () => {
      // Math.max(1, 0) keeps division safe; ratio becomes completed/1.
      expect(() =>
        getPaceStatus({ completed: 5, target: 10, expectedByNow: 0 }),
      ).not.toThrow();
    });

    it("handles target of 0 without infinity in the tolerance term", () => {
      expect(() =>
        getPaceStatus({ completed: 0, target: 0, expectedByNow: 0, leaveDays: 5 }),
      ).not.toThrow();
    });

    it("treats undefined protected fields as zero", () => {
      const a = getPaceStatus({ completed: 90, target: 100, expectedByNow: 100 });
      const b = getPaceStatus({
        completed: 90, target: 100, expectedByNow: 100,
        leaveDays: undefined, publicHolidays: undefined, blockedDays: undefined,
      });
      expect(a).toBe(b);
    });
  });
});
