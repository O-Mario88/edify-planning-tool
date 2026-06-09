import { describe, it, expect } from "vitest";
import { formatUgxShort, formatUgxCompact, formatHumanDate } from "@/lib/format-utils";

describe("formatUgxShort", () => {
  it("formats millions, thousands, and small amounts", () => {
    expect(formatUgxShort(1_500_000)).toBe("UGX 1.5M");
    expect(formatUgxShort(500_000)).toBe("UGX 500K");
    expect(formatUgxShort(250)).toBe("UGX 250");
  });
});

describe("formatUgxCompact", () => {
  it("handles zero and precise millions distinctly from the short form", () => {
    expect(formatUgxCompact(0)).toBe("UGX 0");
    expect(formatUgxCompact(1_250_000)).toBe("UGX 1.25M");
    expect(formatUgxCompact(2_000_000)).toBe("UGX 2M");
  });
});

describe("formatHumanDate", () => {
  it("renders a day-first human date and passes through bad input", () => {
    expect(formatHumanDate("2026-06-06T00:00:00Z")).toMatch(/Jun 2026$/);
    expect(formatHumanDate("not-a-date")).toBe("not-a-date");
  });
});
