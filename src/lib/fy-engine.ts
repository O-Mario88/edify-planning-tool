// Edify Annual Operating Cycle Engine (server-only).
//
// Contract (non-negotiable):
//   • Financial year runs October 1 – September 30.
//   • October 1 initialises a new FY. Previous FY is LOCKED, not deleted.
//   • Annual counters reset for the new FY at FY-scoped record level.
//   • All active schools enter School Improvement Training Gateway.
//   • SSA becomes due only AFTER School Improvement Training is completed.
//   • Full SSA-informed planning requires current-FY SSA Completed + Verified.
//   • Historical data is preserved across every entity.
//
// The pure FY/quarter/cycle math now lives in `@/lib/fy/fy-core` (client-safe).
// This module is the server-only wrapper: it binds the generated ledger and
// keeps the `schoolsMock`-dependent FY summaries + Oct-1 lifecycle utilities.
// Existing zero-arg call sites (activeFinancialYear(), fyForDate(iso), …) are
// preserved.

import "server-only";
import { schoolsMock } from "@/lib/schools-mock";
import {
  generateFinancialYears,
  activeFinancialYear as coreActiveFinancialYear,
  previousFinancialYear as corePreviousFinancialYear,
  nextFinancialYear as coreNextFinancialYear,
  fyForDate as coreFyForDate,
  isInActiveFy as coreIsInActiveFy,
  cycleStatusFor as coreCycleStatusFor,
  cycleLabelFor as coreCycleLabelFor,
  daysSinceCycleStart as coreDaysSinceCycleStart,
  daysUntilCycleEnd as coreDaysUntilCycleEnd,
  cycleRangeLabel as coreCycleRangeLabel,
  ymd,
  addDays,
  type FinancialYear,
  type FinancialYearStatus,
  type CycleStatus,
} from "@/lib/fy/fy-core";

export type { FinancialYear, FinancialYearStatus, CycleStatus };

// ────────── Financial Year ledger (generated, not hardcoded) ──────────
// FY 2025 floor → current operational FY (from engine "now") + one trailing
// Draft FY. With the frozen now (2025-11-15): FY 2025 (Locked), FY 2026
// (Active), FY 2027 (Draft Setup).
export const financialYears: FinancialYear[] = generateFinancialYears();

export function activeFinancialYear(): FinancialYear {
  return coreActiveFinancialYear(financialYears);
}
export function previousFinancialYear(): FinancialYear | undefined {
  return corePreviousFinancialYear(financialYears);
}
export function nextFinancialYear(): FinancialYear | undefined {
  return coreNextFinancialYear(financialYears);
}
export function fyForDate(iso: string): FinancialYear | undefined {
  return coreFyForDate(iso, financialYears);
}
export function isInActiveFy(iso: string): boolean {
  return coreIsInActiveFy(iso, financialYears);
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

// Demo: pre-seed the active FY summary with realistic mid-November state.
function seedSchoolFySummary(activeFyId: string): SchoolFinancialYearSummary[] {
  return schoolsMock.map((s, i) => {
    const mode = i % 7;
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

// ────────── Operational cycle status (bound wrappers over fy-core) ──────────

export function cycleStatusFor(
  iso: string | undefined,
  active: FinancialYear = activeFinancialYear(),
): CycleStatus {
  const previous = financialYears.find((y) =>
    y.endDate === ymd(addDays(new Date(active.startDate), -1)),
  );
  return coreCycleStatusFor(iso, active, previous);
}

export const cycleLabelFor = coreCycleLabelFor;

export function isInCurrentCycle(
  iso: string | undefined,
  active: FinancialYear = activeFinancialYear(),
): boolean {
  return cycleStatusFor(iso, active) === "current_cycle";
}

export function daysSinceCycleStart(
  todayIso: string,
  active: FinancialYear = activeFinancialYear(),
): number {
  return coreDaysSinceCycleStart(todayIso, active);
}

export function daysUntilCycleEnd(
  todayIso: string,
  active: FinancialYear = activeFinancialYear(),
): number {
  return coreDaysUntilCycleEnd(todayIso, active);
}

export function cycleRangeLabel(active: FinancialYear = activeFinancialYear()): string {
  return coreCycleRangeLabel(active);
}
