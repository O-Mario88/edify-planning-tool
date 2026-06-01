// FY + Quarter dropdown options.
//
// Operational cycle is fixed: Oct 1 → Sep 30. The FY ledger is GENERATED in
// `@/lib/fy/fy-core` (floor FY 2025 → current operational FY), so the dropdown
// rolls forward automatically every Oct 1 with no manual edits.
//
// The FY dropdown shows FY 2025 through the current operational FY (the trailing
// Draft/future FY in the ledger is excluded — per spec, options run "from FY
// 2025 to the current operational FY"). The active FY is first (the bar reads
// options[0] as the default). Quarters operate on whichever FY is picked.

import "server-only";

import {
  generateFinancialYears,
  activeFinancialYear as coreActiveFinancialYear,
  quarterDateRangeForFy,
  type FinancialYear,
} from "@/lib/fy/fy-core";
import { ALL_SENTINEL, type FilterOption } from "./types";

// Caption shows the operational range ("Oct 2025 – Sep 2026").
function fyCaption(fy: FinancialYear): string {
  const start = new Date(fy.startDate);
  const end = new Date(fy.endDate);
  const mo = (d: Date) => d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  return `${mo(start)} ${start.getUTCFullYear()} – ${mo(end)} ${end.getUTCFullYear()}`;
}

// Build the FY dropdown: FY 2025 → active (current), active first, then the
// rest newest-first. Future/Draft FYs are excluded from the picker.
export function buildFyOptions(): FilterOption[] {
  const years = generateFinancialYears();
  const active = coreActiveFinancialYear(years);

  const shown = years.filter((y) => y.endDate <= active.endDate); // floor..active
  const others = shown
    .filter((y) => y.id !== active.id)
    .sort((a, b) => b.startDate.localeCompare(a.startDate));
  const ordered = [active, ...others];

  return ordered.map((fy) => ({
    id: fy.id,
    label: fy.label,
    caption: fyCaption(fy),
  }));
}

// Quarters for a given FY id. Q1 = Oct–Dec, Q2 = Jan–Mar, Q3 = Apr–Jun,
// Q4 = Jul–Sep. Returns [All Quarters] + Q1..Q4. Caption shows the month range.
export function buildQuarterOptions(fyId: string): FilterOption[] {
  const years = generateFinancialYears();
  const fy = years.find((y) => y.id === fyId) ?? coreActiveFinancialYear(years);
  const startYear = new Date(fy.startDate).getUTCFullYear();
  const endYear = new Date(fy.endDate).getUTCFullYear();

  return [
    { id: ALL_SENTINEL, label: "All Quarters" },
    { id: "Q1", label: "Q1", caption: `Oct – Dec ${startYear}`, parentKey: fyId },
    { id: "Q2", label: "Q2", caption: `Jan – Mar ${endYear}`, parentKey: fyId },
    { id: "Q3", label: "Q3", caption: `Apr – Jun ${endYear}`, parentKey: fyId },
    { id: "Q4", label: "Q4", caption: `Jul – Sep ${endYear}`, parentKey: fyId },
  ];
}

// Resolve a quarter id ("Q2") + FY id → an ISO date range. Used by the data
// layer (buildDateRangeFromFilters) to scope queries.
export function quarterDateRange(
  fyId: string,
  quarterId: string,
): { startDate: string; endDate: string } | undefined {
  if (quarterId === ALL_SENTINEL) return undefined;
  const fy = generateFinancialYears().find((y) => y.id === fyId);
  if (!fy) return undefined;
  return quarterDateRangeForFy(fy, quarterId);
}
