// 5-tier period pace bands (against expected-cumulative).

import { describe, expect, it } from "vitest";
import { getPeriodPaceStatus } from "@/lib/pace-status";

describe("getPeriodPaceStatus — 5 tiers", () => {
  const expected = 140; // e.g. CCEO Q1 cumulative
  const target = 560;

  it("Ahead at ≥110% of expected", () => {
    expect(getPeriodPaceStatus({ achieved: 154, expected, target })).toBe("Ahead");
  });
  it("On Track at ≥95%", () => {
    expect(getPeriodPaceStatus({ achieved: 133, expected, target })).toBe("On Track");
  });
  it("Slightly Behind at ≥85%", () => {
    expect(getPeriodPaceStatus({ achieved: 119, expected, target })).toBe("Slightly Behind");
  });
  it("Behind at ≥70%", () => {
    expect(getPeriodPaceStatus({ achieved: 98, expected, target })).toBe("Behind");
  });
  it("Critical below 70%", () => {
    expect(getPeriodPaceStatus({ achieved: 90, expected, target })).toBe("Critical");
  });
});
