// Dynamic FY ledger integrity (frozen engine-now = 2025-11-15).

import { describe, expect, it } from "vitest";
import {
  generateFinancialYears,
  endYearForDate,
  activeFinancialYear,
  fyForDate,
  quarterDateRangeForFy,
  cycleStatusFor,
  FLOOR_FY_END_YEAR,
} from "@/lib/fy/fy-core";

describe("endYearForDate — Oct 1 rolls the FY", () => {
  it("rolls correctly across the Oct boundary", () => {
    expect(endYearForDate("2025-11-15")).toBe(2026);
    expect(endYearForDate("2025-10-01")).toBe(2026);
    expect(endYearForDate("2025-09-30")).toBe(2025);
    expect(endYearForDate("2026-01-15")).toBe(2026);
  });
});

describe("generateFinancialYears (now = 2025-11-15)", () => {
  const years = generateFinancialYears("2025-11-15");

  it("floors at FY 2025 and runs to current + one trailing draft", () => {
    expect(FLOOR_FY_END_YEAR).toBe(2025);
    expect(years.map((y) => y.id)).toEqual(["2025", "2026", "2027"]);
    expect(years.map((y) => y.label)).toEqual(["FY 2025", "FY 2026", "FY 2027"]);
  });

  it("active = current operational FY (2026 = Oct 2025 – Sep 2026)", () => {
    const a = activeFinancialYear(years);
    expect(a.id).toBe("2026");
    expect(a.startDate).toBe("2025-10-01");
    expect(a.endDate).toBe("2026-09-30");
  });

  it("statuses: 2025 Locked, 2026 Active, 2027 Draft Setup", () => {
    expect(years.find((y) => y.id === "2025")!.status).toBe("Locked");
    expect(years.find((y) => y.id === "2026")!.status).toBe("Active");
    expect(years.find((y) => y.id === "2027")!.status).toBe("Draft Setup");
  });
});

describe("FY grows automatically every October 1", () => {
  it("Sep 30 2026 → current still FY 2026", () => {
    expect(activeFinancialYear(generateFinancialYears("2026-09-30")).id).toBe("2026");
  });
  it("Oct 1 2026 → a new FY 2027 becomes current", () => {
    const years = generateFinancialYears("2026-10-01");
    expect(activeFinancialYear(years).id).toBe("2027");
    expect(years.map((y) => y.id)).toEqual(["2025", "2026", "2027", "2028"]);
  });
});

describe("fyForDate + quarter ranges (Q1 Oct–Dec … Q4 Jul–Sep)", () => {
  const years = generateFinancialYears("2025-11-15");
  const fy2026 = years.find((y) => y.id === "2026")!;

  it("maps dates into their FY", () => {
    expect(fyForDate("2025-11-15", years)!.id).toBe("2026");
    expect(fyForDate("2025-02-01", years)!.id).toBe("2025");
  });

  it("quarter ranges follow the operational cycle", () => {
    expect(quarterDateRangeForFy(fy2026, "Q1")).toEqual({ startDate: "2025-10-01", endDate: "2025-12-31" });
    expect(quarterDateRangeForFy(fy2026, "Q2")).toEqual({ startDate: "2026-01-01", endDate: "2026-03-31" });
    expect(quarterDateRangeForFy(fy2026, "Q3")).toEqual({ startDate: "2026-04-01", endDate: "2026-06-30" });
    expect(quarterDateRangeForFy(fy2026, "Q4")).toEqual({ startDate: "2026-07-01", endDate: "2026-09-30" });
  });
});

describe("cycleStatusFor buckets dates", () => {
  const years = generateFinancialYears("2025-11-15");
  const active = activeFinancialYear(years); // 2026
  const previous = years.find((y) => y.id === "2025");

  it("current / previous / future / none", () => {
    expect(cycleStatusFor("2025-11-15", active, previous)).toBe("current_cycle");
    expect(cycleStatusFor("2025-02-01", active, previous)).toBe("previous_cycle");
    expect(cycleStatusFor("2030-01-01", active, previous)).toBe("future");
    expect(cycleStatusFor(undefined, active, previous)).toBe("no_entry");
  });
});
