// Cumulative period-target engine.
//
// Targets are CUMULATIVE across the FY, not isolated per quarter:
//   Q1 = 25% · Q2 / Mid-Year = 50% · Q3 = 75% · Q4 / FY = 100% of the FY target.
// Mid-Year is the end of Q2 → 50%. A CCEO with a 560 FY target should be at
// 140 by end-Q1, 280 by mid-year, 420 by end-Q3, 560 by FY end. A PL's lower
// target (280) tracks 70 / 140 / 210 / 280 — never compared to the CCEO number.
//
// `computePeriodTarget` takes the FY target + the selected period and returns
// the expected-cumulative, gap, pace, projection, and risk. Pure & client-safe.

import { engineNowIso } from "@/lib/clock";
import { generateFinancialYears, daysBetween } from "@/lib/fy/fy-core";
import { getPeriodPaceStatus, type PeriodPaceStatus } from "@/lib/pace-status";
import { ALL_SENTINEL } from "@/lib/filters/types";

export type PeriodType = "Q1" | "Q2" | "Q3" | "Q4" | "MidYear" | "FY" | "Month";

export type RiskLevel = "Low" | "Medium" | "High";

// Cumulative expected % by the END of each discrete period.
const CUMULATIVE_PCT: Record<"Q1" | "Q2" | "Q3" | "Q4" | "MidYear", number> = {
  Q1: 0.25,
  Q2: 0.5,
  MidYear: 0.5, // end of Q2
  Q3: 0.75,
  Q4: 1.0,
};

export type PeriodTargetResult = {
  periodType: PeriodType;
  /** Expected cumulative fraction of the FY target by the selected period. */
  expectedPct: number;
  /** Expected cumulative COUNT by the selected period. */
  expectedCumulative: number;
  achieved: number;
  /** Remaining toward the FULL FY target. */
  remaining: number;
  /** achieved / fyTarget, as a 0–100 percentage. */
  achievementPct: number;
  /** achieved − expectedCumulative (negative = behind expected). */
  gapToExpected: number;
  paceStatus: PeriodPaceStatus;
  /** Linear projection of FY-end completion at the current rate. */
  projectedFyCompletion: number;
  riskLevel: RiskLevel;
};

export type ComputePeriodTargetInput = {
  /** Full-FY target for the role (e.g. CCEO 560, PL 280). */
  fyTarget: number;
  /** Selected FY id ("2026") — undefined / ALL falls back to the active FY. */
  selectedFy?: string;
  /** Selected quarter ("Q1".."Q4") — undefined / ALL means FY view. */
  selectedQuarter?: string;
  /** Explicit period override (e.g. "MidYear", "Month"). Wins over quarter. */
  periodType?: PeriodType;
  /** Verified count achieved so far in the selected FY. */
  achieved: number;
  /** ISO "now" — defaults to engine now. */
  now?: string;
  leaveDays?: number;
  publicHolidays?: number;
  blockedDays?: number;
};

function resolvePeriodType(input: ComputePeriodTargetInput): PeriodType {
  if (input.periodType) return input.periodType;
  const q = input.selectedQuarter;
  if (q && q !== ALL_SENTINEL && /^Q[1-4]$/.test(q)) return q as PeriodType;
  return "FY";
}

export function computePeriodTarget(input: ComputePeriodTargetInput): PeriodTargetResult {
  const now = input.now ?? engineNowIso();
  const years = generateFinancialYears(now);
  const fy =
    (input.selectedFy && input.selectedFy !== ALL_SENTINEL
      ? years.find((y) => y.id === input.selectedFy)
      : undefined) ?? years.find((y) => y.status === "Active") ?? years[0];

  const periodType = resolvePeriodType(input);

  // Time-elapsed fraction of the selected FY at `now`, clamped to [0,1].
  const totalDays = Math.max(1, daysBetween(fy.startDate, fy.endDate));
  const clampedNow = now < fy.startDate ? fy.startDate : now > fy.endDate ? fy.endDate : now;
  const elapsedFraction = Math.min(1, Math.max(0, daysBetween(fy.startDate, clampedNow) / totalDays));

  // Discrete period → cumulative % from the table; FY/Month → time-elapsed.
  const expectedPct =
    periodType === "FY" || periodType === "Month"
      ? elapsedFraction
      : CUMULATIVE_PCT[periodType];

  const expectedCumulative = Math.round(input.fyTarget * expectedPct);
  const achieved = input.achieved;
  const remaining = Math.max(0, input.fyTarget - achieved);
  const achievementPct = input.fyTarget > 0 ? (achieved / input.fyTarget) * 100 : 0;
  const gapToExpected = achieved - expectedCumulative;

  const paceStatus = getPeriodPaceStatus({
    achieved,
    expected: expectedCumulative,
    target: input.fyTarget,
    leaveDays: input.leaveDays,
    publicHolidays: input.publicHolidays,
    blockedDays: input.blockedDays,
  });

  // Projection: discrete period → scale by its cumulative %; FY view → by
  // time elapsed. Both estimate FY-end completion at the current pace.
  const projectedFyCompletion =
    periodType === "FY" || periodType === "Month"
      ? elapsedFraction > 0
        ? Math.round(achieved / elapsedFraction)
        : achieved
      : expectedPct > 0
        ? Math.round(achieved / expectedPct)
        : achieved;

  const projRatio = input.fyTarget > 0 ? projectedFyCompletion / input.fyTarget : 1;
  const riskLevel: RiskLevel = projRatio >= 1 ? "Low" : projRatio >= 0.85 ? "Medium" : "High";

  return {
    periodType,
    expectedPct,
    expectedCumulative,
    achieved,
    remaining,
    achievementPct,
    gapToExpected,
    paceStatus,
    projectedFyCompletion,
    riskLevel,
  };
}
