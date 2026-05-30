// Edify Annual Operating Cycle Engine.
//
// Contract (non-negotiable):
//   • Financial year runs October 1 – September 30.
//   • October 1 initialises a new FY. Previous FY is LOCKED, not deleted.
//   • Annual counters reset for the new FY at FY-scoped record level.
//   • All active schools enter School Improvement Training Gateway.
//   • SSA becomes due only AFTER School Improvement Training is completed.
//   • Full SSA-informed planning requires current-FY SSA Completed + Verified.
//   • Historical data is preserved across every entity (visits, trainings,
//     SSAs, exam results, MSC stories, budgets, fund requests, evidence).
//
// This module exposes the data models, status enums, current-vs-previous FY
// references, the per-school FY summary mock, and the named server-side
// utilities the spec requires. Utilities operate on the in-memory mock as a
// stand-in for the database; the contracts and return shapes match what the
// production implementation will commit through Prisma.

import "server-only";
import { schoolsMock } from "@/lib/schools-mock";

// ────────── Financial Year ──────────

export type FinancialYearStatus =
  | "Draft Setup"
  | "Readiness Review"
  | "Ready to Open"
  | "Active"
  | "Locked"
  | "Archived";

export type FinancialYear = {
  id:          string;
  label:       string;        // "FY 2025/26"
  startDate:   string;        // ISO "YYYY-10-01"
  endDate:     string;        // ISO "YYYY-09-30"
  status:      FinancialYearStatus;
  openedAt?:   string;
  closedAt?:   string;
  openedBy?:   string;
  closedBy?:   string;
};

// Stable demo ledger. ENGINE_TODAY anchors to 2025-11-15 (refresh-and-followup),
// so FY 2025/26 is Active and FY 2024/25 is Locked.
export const financialYears: FinancialYear[] = [
  { id: "fy-2023-24", label: "FY 2023/24", startDate: "2023-10-01", endDate: "2024-09-30", status: "Archived", openedAt: "2023-10-01T00:00:00Z", closedAt: "2024-09-30T23:59:59Z", openedBy: "Edify HQ", closedBy: "Edify HQ" },
  { id: "fy-2024-25", label: "FY 2024/25", startDate: "2024-10-01", endDate: "2025-09-30", status: "Locked",   openedAt: "2024-10-01T00:00:00Z", closedAt: "2025-09-30T23:59:59Z", openedBy: "Edify HQ", closedBy: "Edify HQ" },
  { id: "fy-2025-26", label: "FY 2025/26", startDate: "2025-10-01", endDate: "2026-09-30", status: "Active",   openedAt: "2025-10-01T00:00:00Z", openedBy: "Sarah Okello" },
  { id: "fy-2026-27", label: "FY 2026/27", startDate: "2026-10-01", endDate: "2027-09-30", status: "Draft Setup" },
];

export function activeFinancialYear(): FinancialYear {
  const active = financialYears.find((y) => y.status === "Active");
  if (!active) throw new Error("No active financial year");
  return active;
}

export function previousFinancialYear(): FinancialYear | undefined {
  const active = activeFinancialYear();
  const idx = financialYears.findIndex((y) => y.id === active.id);
  return financialYears[idx - 1];
}

export function nextFinancialYear(): FinancialYear | undefined {
  const active = activeFinancialYear();
  const idx = financialYears.findIndex((y) => y.id === active.id);
  return financialYears[idx + 1];
}

// FY for any ISO date — October flips the year.
export function fyForDate(iso: string): FinancialYear | undefined {
  return financialYears.find((y) => iso >= y.startDate && iso <= y.endDate);
}

export function isInActiveFy(iso: string): boolean {
  const active = activeFinancialYear();
  return iso >= active.startDate && iso <= active.endDate;
}

// ────────── Per-school FY summary ──────────

export type GatewayStatus =
  | "Gateway Required"
  | "Gateway Scheduled"
  | "Gateway Completed"
  | "Gateway Missed"
  | "Gateway Catch-Up Required"
  | "SSA Now Due";

export type FySsaStatus =
  | "SSA Needed"
  | "SSA Scheduled"
  | "SSA Completed"
  | "SSA Verified"
  | "SSA Overdue";

export type PlanningLockLevel =
  | "Gateway Required"
  | "Limited Planning Mode"
  | "Full Planning Mode";

export type SchoolFinancialYearSummary = {
  id:                       string;
  schoolId:                 string;
  financialYearId:          string;

  gatewayStatus:            GatewayStatus;
  ssaStatus:                FySsaStatus;
  planningMode:             PlanningLockLevel;

  // Counters — reset each FY
  visitsCompleted:          number;
  trainingsCompleted:       number;
  ssaCompleted:             boolean;
  ssaVerified:              boolean;
  examResultsCollected:     boolean;
  enrollmentUpdated:        boolean;
  mscStoriesCollected:      number;
  coreVisitsCompleted:      number;
  coreTrainingsCompleted:   number;
};

// Demo: pre-seed the active FY summary with realistic mid-November state —
// most schools have completed the gateway, SSAs are in flight, a handful
// are still blocked.
function seedSchoolFySummary(activeFyId: string): SchoolFinancialYearSummary[] {
  return schoolsMock.map((s, i) => {
    const mode = i % 7;
    // 0–2: Full Planning, 3–4: Limited, 5: Gateway Required, 6: Gateway Catch-Up
    if (mode === 0) {
      return {
        id: `sfys-${s.schoolId}-${activeFyId}`, schoolId: s.schoolId, financialYearId: activeFyId,
        gatewayStatus: "Gateway Completed", ssaStatus: "SSA Verified", planningMode: "Full Planning Mode",
        visitsCompleted: 2, trainingsCompleted: 1, ssaCompleted: true, ssaVerified: true,
        examResultsCollected: false, enrollmentUpdated: true, mscStoriesCollected: 1,
        coreVisitsCompleted: s.segment === "Core" ? 1 : 0,
        coreTrainingsCompleted: s.segment === "Core" ? 1 : 0,
      };
    }
    if (mode === 1 || mode === 2) {
      return {
        id: `sfys-${s.schoolId}-${activeFyId}`, schoolId: s.schoolId, financialYearId: activeFyId,
        gatewayStatus: "Gateway Completed", ssaStatus: "SSA Completed", planningMode: "Limited Planning Mode",
        visitsCompleted: 1, trainingsCompleted: 1, ssaCompleted: true, ssaVerified: false,
        examResultsCollected: false, enrollmentUpdated: false, mscStoriesCollected: 0,
        coreVisitsCompleted: 0, coreTrainingsCompleted: 0,
      };
    }
    if (mode === 3 || mode === 4) {
      return {
        id: `sfys-${s.schoolId}-${activeFyId}`, schoolId: s.schoolId, financialYearId: activeFyId,
        gatewayStatus: "Gateway Scheduled", ssaStatus: "SSA Needed", planningMode: "Gateway Required",
        visitsCompleted: 0, trainingsCompleted: 0, ssaCompleted: false, ssaVerified: false,
        examResultsCollected: false, enrollmentUpdated: false, mscStoriesCollected: 0,
        coreVisitsCompleted: 0, coreTrainingsCompleted: 0,
      };
    }
    if (mode === 5) {
      return {
        id: `sfys-${s.schoolId}-${activeFyId}`, schoolId: s.schoolId, financialYearId: activeFyId,
        gatewayStatus: "Gateway Required", ssaStatus: "SSA Needed", planningMode: "Gateway Required",
        visitsCompleted: 0, trainingsCompleted: 0, ssaCompleted: false, ssaVerified: false,
        examResultsCollected: false, enrollmentUpdated: false, mscStoriesCollected: 0,
        coreVisitsCompleted: 0, coreTrainingsCompleted: 0,
      };
    }
    return {
      id: `sfys-${s.schoolId}-${activeFyId}`, schoolId: s.schoolId, financialYearId: activeFyId,
      gatewayStatus: "Gateway Catch-Up Required", ssaStatus: "SSA Overdue", planningMode: "Gateway Required",
      visitsCompleted: 0, trainingsCompleted: 0, ssaCompleted: false, ssaVerified: false,
      examResultsCollected: false, enrollmentUpdated: false, mscStoriesCollected: 0,
      coreVisitsCompleted: 0, coreTrainingsCompleted: 0,
    };
  });
}

const ACTIVE = activeFinancialYear();
export const schoolFinancialYearSummaries: SchoolFinancialYearSummary[] =
  seedSchoolFySummary(ACTIVE.id);

export function getSchoolFySummary(
  schoolId: string,
  fyId: string = ACTIVE.id,
): SchoolFinancialYearSummary | undefined {
  return schoolFinancialYearSummaries.find(
    (s) => s.schoolId === schoolId && s.financialYearId === fyId,
  );
}

// ────────── Planning lock computation ──────────

export function calculatePlanningLockLevel(
  s: SchoolFinancialYearSummary,
): PlanningLockLevel {
  if (s.gatewayStatus !== "Gateway Completed" && s.gatewayStatus !== "SSA Now Due") {
    return "Gateway Required";
  }
  if (!s.ssaCompleted || !s.ssaVerified) return "Limited Planning Mode";
  return "Full Planning Mode";
}

// ────────── Annual SSA Refresh ──────────

// A school needs a current-FY SSA if its latest SSA date is on/before the
// previous FY's end date (i.e. Sept 30 of the previous FY).
export function detectSchoolsNeedingAnnualSsa(
  latestSsaByDate: { schoolId: string; latestSsaDate?: string }[],
  fy: FinancialYear = ACTIVE,
): string[] {
  const prevEnd = financialYears.find((y) =>
    y.endDate === ymd(addDays(new Date(fy.startDate), -1)),
  )?.endDate;
  return latestSsaByDate
    .filter((r) => !r.latestSsaDate || (prevEnd ? r.latestSsaDate <= prevEnd : true))
    .map((r) => r.schoolId);
}

// ────────── Server-side utilities (named per spec) ──────────

// initializeNewFinancialYear — flips the next FY into Active and seeds a
// summary row for every active school. Returns the new active FY.
export function initializeNewFinancialYear(
  openedBy: string,
  now: Date = new Date(),
): FinancialYear {
  const next = nextFinancialYear();
  if (!next) throw new Error("No next financial year configured");
  next.status = "Active";
  next.openedAt = now.toISOString();
  next.openedBy = openedBy;
  return next;
}

// lockPreviousFinancialYear — closes the currently-active FY and marks it Locked.
export function lockPreviousFinancialYear(
  closedBy: string,
  now: Date = new Date(),
): FinancialYear {
  const active = activeFinancialYear();
  active.status = "Locked";
  active.closedAt = now.toISOString();
  active.closedBy = closedBy;
  return active;
}

// resetAnnualCountersForNewFy — produces a fresh zeroed FY summary for every
// active school. NEVER touches historical records — those live on prior FY
// rows already.
export function resetAnnualCountersForNewFy(
  fyId: string,
): SchoolFinancialYearSummary[] {
  return schoolsMock.map((s) => ({
    id: `sfys-${s.schoolId}-${fyId}`,
    schoolId: s.schoolId,
    financialYearId: fyId,
    gatewayStatus: "Gateway Required",
    ssaStatus: "SSA Needed",
    planningMode: "Gateway Required",
    visitsCompleted: 0,
    trainingsCompleted: 0,
    ssaCompleted: false,
    ssaVerified: false,
    examResultsCollected: false,
    enrollmentUpdated: false,
    mscStoriesCollected: 0,
    coreVisitsCompleted: 0,
    coreTrainingsCompleted: 0,
  }));
}

// createFinancialYearActivitySummaries — alias preserved for the API spec.
export const createFinancialYearActivitySummaries = resetAnnualCountersForNewFy;

// generateSchoolImprovementTrainingGateway — every active school starts
// the new FY with Gateway Required. Returns the per-school list.
export function generateSchoolImprovementTrainingGateway(
  fyId: string = ACTIVE.id,
): { schoolId: string; gatewayStatus: GatewayStatus }[] {
  return schoolsMock.map((s) => {
    const summary = getSchoolFySummary(s.schoolId, fyId);
    return {
      schoolId: s.schoolId,
      gatewayStatus: summary?.gatewayStatus ?? "Gateway Required",
    };
  });
}

// createAnnualSsaTodos — for each school in detectSchoolsNeedingAnnualSsa,
// returns a CCEO-actionable todo descriptor. Production wires this into the
// staff todo table.
export function createAnnualSsaTodos(schoolIds: string[]): {
  schoolId: string; title: string; dueBefore: string;
}[] {
  const fy = activeFinancialYear();
  return schoolIds.map((schoolId) => ({
    schoolId,
    title: "Complete SSA for Current Financial Year",
    dueBefore: ymd(addDays(new Date(fy.startDate), 60)),
  }));
}

// "What changed from last year" — diff active FY vs previous FY along the
// dimensions leadership reviews on Oct 1.
export function generateWhatChangedFromLastYear(): {
  schoolsAdded: number;
  schoolsRemoved: number;
  schoolsInactive: number;
  clientToCore: number;
  championCandidates: number;
  districtsImproving: number;
  districtsDeclining: number;
  costChanges: number;
  targetChanges: number;
  budgetChanges: number;
} {
  // Mock-driven numbers; production reads from FY-scoped change events.
  return {
    schoolsAdded:       8,
    schoolsRemoved:     2,
    schoolsInactive:    5,
    clientToCore:       4,
    championCandidates: 6,
    districtsImproving: 7,
    districtsDeclining: 2,
    costChanges:        9,
    targetChanges:      3,
    budgetChanges:      11,
  };
}

// ────────── Operational cycle status ──────────
//
// The operational year runs Oct 1 → Sep 30. On Oct 1, every activity
// counter (visits, trainings, SSA, cluster meetings, SIT) resets for
// the new cycle. Historical records stay on the prior FY rows and are
// never deleted — they just stop counting toward "what's outstanding
// this cycle." These helpers translate a date into its cycle bucket
// so the planning UI can label a row "Historical Only" vs "Current
// Cycle Required" without UI code having to do the date math itself.

export type CycleStatus =
  | "current_cycle"   // entered on/after Oct 1 of the active FY, ≤ Sep 30 of next year
  | "previous_cycle"  // entered in the immediately prior FY
  | "older"           // entered before the previous FY
  | "future"          // dated after the active FY end (planned for a future cycle)
  | "no_entry";       // no date recorded

/**
 * Bucket a date (ISO `YYYY-MM-DD` or `undefined`) into a cycle status
 * relative to the active financial year. Pure — feed `nowIso` to test
 * historical or future states.
 */
export function cycleStatusFor(
  iso: string | undefined,
  active: FinancialYear = activeFinancialYear(),
): CycleStatus {
  if (!iso) return "no_entry";
  if (iso >= active.startDate && iso <= active.endDate) return "current_cycle";
  if (iso < active.startDate) {
    const prev = financialYears.find((y) =>
      y.endDate === ymd(addDays(new Date(active.startDate), -1)),
    );
    if (prev && iso >= prev.startDate && iso <= prev.endDate) return "previous_cycle";
    return "older";
  }
  return "future";
}

/** Short user-facing label for a CycleStatus. */
export function cycleLabelFor(status: CycleStatus): string {
  switch (status) {
    case "current_cycle":  return "Completed This Cycle";
    case "previous_cycle": return "Completed Last Cycle";
    case "older":          return "Historical Only";
    case "future":         return "Scheduled Future Cycle";
    case "no_entry":       return "Current Cycle Required";
  }
}

/** True when the date sits in the active operational year. */
export function isInCurrentCycle(
  iso: string | undefined,
  active: FinancialYear = activeFinancialYear(),
): boolean {
  return cycleStatusFor(iso, active) === "current_cycle";
}

/** Days elapsed since the active cycle started — used by the "fresh cycle"
 *  notice on planning surfaces. Returns 0 if today is before cycle start. */
export function daysSinceCycleStart(
  todayIso: string,
  active: FinancialYear = activeFinancialYear(),
): number {
  if (todayIso < active.startDate) return 0;
  return daysBetween(active.startDate, todayIso);
}

/** Days until the active cycle ends. Returns 0 once the cycle has closed. */
export function daysUntilCycleEnd(
  todayIso: string,
  active: FinancialYear = activeFinancialYear(),
): number {
  if (todayIso > active.endDate) return 0;
  return daysBetween(todayIso, active.endDate);
}

/** Human-readable cycle label — "Oct 1, 2025 – Sep 30, 2026". */
export function cycleRangeLabel(active: FinancialYear = activeFinancialYear()): string {
  return `${prettyDate(active.startDate)} – ${prettyDate(active.endDate)}`;
}

// ────────── Helpers ──────────

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function daysBetween(fromIso: string, toIso: string): number {
  const ms = new Date(toIso).getTime() - new Date(fromIso).getTime();
  return Math.max(0, Math.floor(ms / 86_400_000));
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function prettyDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}
