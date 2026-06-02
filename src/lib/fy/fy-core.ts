// Pure fiscal-year math — the single source of FY/quarter/cycle truth.
//
// Operational cycle: October 1 → September 30. A FY is named by its END
// calendar year: "FY 2026" = Oct 1 2025 → Sep 30 2026. The ledger is GENERATED
// (not hardcoded) from a floor of FY 2025 up to the current operational FY, so
// it grows automatically every October 1 with no manual edits.
//
// This module is PURE and client-safe (no `server-only`, no mock imports), so
// both server code (fy-engine, fy-options) and client cards can share it. The
// server-only `fy-engine.ts` wraps these with zero-arg signatures bound to the
// live ledger; `fy-options.ts` builds the dropdown from here.

import { engineNowIso } from "@/lib/clock";

// ────────── Types (shape preserved from the old fy-engine ledger) ──────────

export type FinancialYearStatus =
  | "Draft Setup"
  | "Readiness Review"
  | "Ready to Open"
  | "Active"
  | "Locked"
  | "Archived";

export type FinancialYear = {
  id: string; // end-year string, e.g. "2026"
  label: string; // "FY 2026"
  startDate: string; // ISO "YYYY-10-01"
  endDate: string; // ISO "YYYY-09-30"
  status: FinancialYearStatus;
  openedAt?: string;
  closedAt?: string;
  openedBy?: string;
  closedBy?: string;
};

export type CycleStatus =
  | "current_cycle"
  | "previous_cycle"
  | "older"
  | "future"
  | "no_entry";

// ────────── Date helpers (pure) ──────────

export function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

export function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function daysBetween(fromIso: string, toIso: string): number {
  const ms = new Date(toIso).getTime() - new Date(fromIso).getTime();
  return Math.max(0, Math.floor(ms / 86_400_000));
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function prettyDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

// ────────── FY identity ──────────

/** End (calendar) year of the FY a date falls in. Oct–Dec roll to next year. */
export function endYearForDate(iso: string): number {
  const [y, m] = iso.split("-").map(Number);
  return m >= 10 ? y + 1 : y; // October (month 10) starts the next FY
}

export function fyIdForEndYear(endYear: number): string {
  return String(endYear);
}

export function fyLabelForEndYear(endYear: number): string {
  return `FY ${endYear}`;
}

export function makeFinancialYear(endYear: number, status: FinancialYearStatus): FinancialYear {
  const startDate = `${endYear - 1}-10-01`;
  const endDate = `${endYear}-09-30`;
  const fy: FinancialYear = {
    id: fyIdForEndYear(endYear),
    label: fyLabelForEndYear(endYear),
    startDate,
    endDate,
    status,
  };
  if (status === "Active" || status === "Locked" || status === "Archived") {
    fy.openedAt = `${startDate}T00:00:00Z`;
    fy.openedBy = "Edify HQ";
  }
  if (status === "Locked" || status === "Archived") {
    fy.closedAt = `${endDate}T23:59:59Z`;
    fy.closedBy = "Edify HQ";
  }
  return fy;
}

// ────────── Ledger generation ──────────

/** Lowest FY the system tracks: FY 2025 = Oct 2024 – Sep 2025. */
export const FLOOR_FY_END_YEAR = 2025;

/**
 * Generate the FY ledger from the floor (FY 2025) up to the current
 * operational FY (derived from `nowIso`), plus one trailing Draft FY so the
 * Oct-1 lifecycle functions (next FY / initialize) keep working. Grows
 * automatically: once `now` reaches Oct 1, `endYearForDate` rolls and a new
 * Active FY appears.
 */
export function generateFinancialYears(nowIso: string = engineNowIso()): FinancialYear[] {
  const current = Math.max(FLOOR_FY_END_YEAR, endYearForDate(nowIso));
  const years: FinancialYear[] = [];
  for (let end = FLOOR_FY_END_YEAR; end <= current; end++) {
    const status: FinancialYearStatus =
      end === current ? "Active" : end === current - 1 ? "Locked" : "Archived";
    years.push(makeFinancialYear(end, status));
  }
  // One trailing FY in setup so nextFinancialYear()/initialize work.
  years.push(makeFinancialYear(current + 1, "Draft Setup"));
  return years;
}

// ────────── Pure resolvers (take the ledger explicitly) ──────────

export function activeFinancialYear(years: FinancialYear[]): FinancialYear {
  const active = years.find((y) => y.status === "Active");
  if (!active) throw new Error("No active financial year");
  return active;
}

export function previousFinancialYear(years: FinancialYear[]): FinancialYear | undefined {
  const active = activeFinancialYear(years);
  const idx = years.findIndex((y) => y.id === active.id);
  return years[idx - 1];
}

export function nextFinancialYear(years: FinancialYear[]): FinancialYear | undefined {
  const active = activeFinancialYear(years);
  const idx = years.findIndex((y) => y.id === active.id);
  return years[idx + 1];
}

export function fyForDate(iso: string, years: FinancialYear[]): FinancialYear | undefined {
  return years.find((y) => iso >= y.startDate && iso <= y.endDate);
}

export function isInActiveFy(iso: string, years: FinancialYear[]): boolean {
  const active = activeFinancialYear(years);
  return iso >= active.startDate && iso <= active.endDate;
}

// ────────── Quarter ranges ──────────
// Q1 = Oct–Dec (start year), Q2 = Jan–Mar, Q3 = Apr–Jun, Q4 = Jul–Sep (end year).
//
// SINGLE SOURCE OF TRUTH for quarter → month labels. Every surface that shows a
// quarter (period selectors, target cards, SSA trends, fund filters, …) must
// derive its label from these helpers so the calendar can never drift again.

export type QuarterId = "Q1" | "Q2" | "Q3" | "Q4";

/** Month span of each quarter, en-dash, no spaces — for inline parentheticals. */
export const QUARTER_MONTH_RANGE: Record<QuarterId, string> = {
  Q1: "Oct–Dec",
  Q2: "Jan–Mar",
  Q3: "Apr–Jun",
  Q4: "Jul–Sep",
};

/** Mid-Year = end of Q2 → cumulative Oct–Mar. Full-Year = Oct–Sep. */
export const MID_YEAR_MONTH_RANGE = "Oct–Mar";
export const FULL_YEAR_MONTH_RANGE = "Oct–Sep";

/** "Oct–Dec" for a quarter id (empty for an unknown id). */
export function quarterMonthRange(quarterId: string): string {
  return QUARTER_MONTH_RANGE[quarterId as QuarterId] ?? "";
}

/** "Q1 (Oct–Dec)" — the canonical quarter label used across the app. */
export function quarterLabel(quarterId: string): string {
  const range = QUARTER_MONTH_RANGE[quarterId as QuarterId];
  return range ? `${quarterId} (${range})` : quarterId;
}

/** Which quarter a date falls in (FY is Oct-start). */
export function quarterIdForDate(iso: string): QuarterId {
  const m = Number(iso.slice(5, 7));
  if (m >= 10 && m <= 12) return "Q1";
  if (m >= 1 && m <= 3) return "Q2";
  if (m >= 4 && m <= 6) return "Q3";
  return "Q4";
}

export function quarterDateRangeForFy(
  fy: FinancialYear,
  quarterId: string,
): { startDate: string; endDate: string } | undefined {
  const startYear = new Date(fy.startDate).getUTCFullYear();
  const endYear = new Date(fy.endDate).getUTCFullYear();
  switch (quarterId) {
    case "Q1": return { startDate: `${startYear}-10-01`, endDate: `${startYear}-12-31` };
    case "Q2": return { startDate: `${endYear}-01-01`, endDate: `${endYear}-03-31` };
    case "Q3": return { startDate: `${endYear}-04-01`, endDate: `${endYear}-06-30` };
    case "Q4": return { startDate: `${endYear}-07-01`, endDate: `${endYear}-09-30` };
    default: return undefined;
  }
}

// ────────── Cycle status (pure) ──────────

export function cycleStatusFor(
  iso: string | undefined,
  active: FinancialYear,
  previous?: FinancialYear,
): CycleStatus {
  if (!iso) return "no_entry";
  if (iso >= active.startDate && iso <= active.endDate) return "current_cycle";
  if (iso < active.startDate) {
    if (previous && iso >= previous.startDate && iso <= previous.endDate) return "previous_cycle";
    return "older";
  }
  return "future";
}

export function cycleLabelFor(status: CycleStatus): string {
  switch (status) {
    case "current_cycle": return "Completed This Cycle";
    case "previous_cycle": return "Completed Last Cycle";
    case "older": return "Historical Only";
    case "future": return "Scheduled Future Cycle";
    case "no_entry": return "Current Cycle Required";
  }
}

export function isInCurrentCycle(
  iso: string | undefined,
  active: FinancialYear,
): boolean {
  return cycleStatusFor(iso, active) === "current_cycle";
}

export function daysSinceCycleStart(todayIso: string, active: FinancialYear): number {
  if (todayIso < active.startDate) return 0;
  return daysBetween(active.startDate, todayIso);
}

export function daysUntilCycleEnd(todayIso: string, active: FinancialYear): number {
  if (todayIso > active.endDate) return 0;
  return daysBetween(todayIso, active.endDate);
}

export function cycleRangeLabel(active: FinancialYear): string {
  return `${prettyDate(active.startDate)} – ${prettyDate(active.endDate)}`;
}
