// Operating-targets engine.
//
// Powers the "My Targets" dashboard for CCEO + PL (their personal
// scorecard) and the "Team Targets" view for PL / CD / HR / IA (the
// same scorecard, but summed across the CCEO team they oversee). One
// engine, one component, three audiences — that way Mid-Year / FY
// roll-ups behave identically and a PL drilling into "Team Targets"
// always sees numbers that match what each CCEO sees in "My Targets".
//
// Icons are referenced by string key here (not as Lucide components)
// so this module is safe to import from server components — the view
// resolves the key against an icon map on the client side.

export type PeriodKey = "monthly" | "q1" | "q2" | "midYear" | "q3" | "q4" | "fy";

export type Status = "On Track" | "At Risk" | "Off Track" | "Not Started";

export type MetricIconKey =
  | "building2"
  | "graduationCap"
  | "activity"
  | "checkCircle2"
  | "clipboardCheck"
  | "wallet";

export type MetricRow = {
  key:       string;
  label:     string;
  iconKey:   MetricIconKey;
  iconBg:    string;
  iconText:  string;
  /** Tiny last-12-week trend used for the KPI card sparkline. */
  trend:     number[];
  /** Target + achieved per period. Mid-Year + FY are computed at read
   *  time from the quarter rows, so the data here only specifies the
   *  raw monthly + quarter inputs. */
  monthly:   { target: number; achieved: number };
  q1:        { target: number; achieved: number };
  q2:        { target: number; achieved: number };
  q3:        { target: number; achieved: number };
  q4:        { target: number; achieved: number };
};

export type PeriodCell = { target: number; achieved: number; pct: number; status: Status };

export type ComputedRow = MetricRow & {
  cells: Record<PeriodKey, PeriodCell>;
  overallPct: number;
};

// ────────── Status classification ──────────
//
// On Track ≥70 · At Risk 50-69 · Off Track <50 · Not Started has no
// data (used for future quarters where the cycle hasn't begun).
export function classify(pct: number, started: boolean): Status {
  if (!started) return "Not Started";
  if (pct >= 70) return "On Track";
  if (pct >= 50) return "At Risk";
  return "Off Track";
}

// ────────── Period metadata ──────────

export const PERIODS: { key: PeriodKey; label: string; sub: string; band: string; tone: string }[] = [
  { key: "monthly", label: "Nov 2025",   sub: "MONTHLY",    band: "bg-slate-50",  tone: "text-slate-700" },
  { key: "q1",      label: "Q1 (Oct–Dec)", sub: "QUARTER 1", band: "bg-emerald-50/50", tone: "text-emerald-700" },
  { key: "q2",      label: "Q2 (Jan–Mar)", sub: "QUARTER 2", band: "bg-blue-50/50",    tone: "text-blue-700" },
  { key: "midYear", label: "MID YEAR",     sub: "Oct – Mar", band: "bg-violet-50/60",  tone: "text-violet-700" },
  { key: "q3",      label: "Q3 (Apr–Jun)", sub: "QUARTER 3", band: "bg-amber-50/40",   tone: "text-amber-700" },
  { key: "q4",      label: "Q4 (Jul–Sep)", sub: "QUARTER 4", band: "bg-rose-50/40",    tone: "text-rose-700" },
  { key: "fy",      label: "FY 2025/26",   sub: "FULL YEAR", band: "bg-indigo-50/40",  tone: "text-indigo-700" },
];

// ────────── Compute ──────────

function pct(achieved: number, target: number): number {
  if (target <= 0) return 0;
  return Math.round((achieved / target) * 100);
}

export function computeRow(m: MetricRow, startedPeriods: Record<PeriodKey, boolean>): ComputedRow {
  const cells: Record<PeriodKey, PeriodCell> = {} as Record<PeriodKey, PeriodCell>;
  const make = (target: number, achieved: number, key: PeriodKey): PeriodCell => {
    const p = pct(achieved, target);
    return { target, achieved, pct: p, status: classify(p, startedPeriods[key]) };
  };
  cells.monthly = make(m.monthly.target,  m.monthly.achieved,  "monthly");
  cells.q1      = make(m.q1.target,       m.q1.achieved,       "q1");
  cells.q2      = make(m.q2.target,       m.q2.achieved,       "q2");
  cells.q3      = make(m.q3.target,       m.q3.achieved,       "q3");
  cells.q4      = make(m.q4.target,       m.q4.achieved,       "q4");
  const myTarget   = m.q1.target   + m.q2.target;
  const myAchieved = m.q1.achieved + m.q2.achieved;
  cells.midYear = make(myTarget, myAchieved, "midYear");
  const fyTarget   = m.q1.target   + m.q2.target   + m.q3.target   + m.q4.target;
  const fyAchieved = m.q1.achieved + m.q2.achieved + m.q3.achieved + m.q4.achieved;
  cells.fy      = make(fyTarget, fyAchieved, "fy");
  return { ...m, cells, overallPct: cells.fy.pct };
}

export type OperatingTargets = {
  scope:           string;        // e.g. "My Targets" / "Team Targets"
  audience:        string;        // e.g. "Country Program Lead" / "CCEO"
  fiscalYearLabel: string;        // "FY 2025/26"
  periodLabel:    string;         // "Nov 1 – Nov 30, 2025"
  lastUpdated:    string;         // "Nov 14, 2025 8:30 AM"
  daysCompleted: { done: number; total: number };
  /** Which periods have started (drives status classification). */
  startedPeriods: Record<PeriodKey, boolean>;
  /** Raw metric rows — computed per render. */
  metrics:        MetricRow[];
  /** Cumulative trend over months — actual vs target for the trend chart. */
  trend:          { label: string; actual: number; target: number }[];
  /** Top areas of focus surfaced on the bottom-right card. */
  topFocus:       { rank: number; label: string; detail: string; status: Status }[];
};

// ────────── Seed data — CCEO personal scorecard ──────────
//
// Numbers match the attached "My Targets" reference. Mid-Year and FY
// columns are derived (Mid-Year = Q1 + Q2 · FY = Q1 + Q2 + Q3 + Q4).
const cceoMetrics: MetricRow[] = [
  { key: "schools",   label: "Schools Visited",       iconKey: "building2",      iconBg: "bg-blue-100",    iconText: "text-blue-700",
    trend: [40, 42, 50, 55, 58, 60, 62, 60, 68, 70, 72, 74],
    monthly: { target: 60, achieved: 42 }, q1: { target: 150, achieved: 122 }, q2: { target: 150, achieved: 92 },  q3: { target: 150, achieved: 0 }, q4: { target: 180, achieved: 0 } },
  { key: "trainings", label: "Trainings Delivered",    iconKey: "graduationCap",  iconBg: "bg-emerald-100", iconText: "text-emerald-700",
    trend: [9, 10, 11, 11, 12, 12, 13, 13, 12, 14, 13, 14],
    monthly: { target: 20, achieved: 14 }, q1: { target: 50,  achieved: 36 },  q2: { target: 50,  achieved: 27 },  q3: { target: 50,  achieved: 0 }, q4: { target: 50,  achieved: 0 } },
  { key: "ssa",       label: "SSA Visits Completed",  iconKey: "activity",       iconBg: "bg-violet-100",  iconText: "text-violet-700",
    trend: [11, 9, 12, 10, 13, 11, 14, 10, 12, 13, 12, 12],
    monthly: { target: 20, achieved: 12 }, q1: { target: 51,  achieved: 34 },  q2: { target: 56,  achieved: 32 },  q3: { target: 56,  achieved: 0 }, q4: { target: 58,  achieved: 0 } },
  { key: "followups", label: "Follow-ups Closed",     iconKey: "checkCircle2",   iconBg: "bg-cyan-100",    iconText: "text-cyan-700",
    trend: [4, 6, 7, 8, 9, 10, 11, 10, 11, 11, 12, 11],
    monthly: { target: 14, achieved: 11 }, q1: { target: 24,  achieved: 18 },  q2: { target: 27,  achieved: 14 },  q3: { target: 25,  achieved: 0 }, q4: { target: 28,  achieved: 0 } },
  { key: "plans",     label: "Plan Approvals",        iconKey: "clipboardCheck", iconBg: "bg-amber-100",   iconText: "text-amber-700",
    trend: [2, 3, 4, 4, 5, 5, 6, 6, 7, 7, 7, 7],
    monthly: { target: 10, achieved: 7 },  q1: { target: 24,  achieved: 17 },  q2: { target: 16,  achieved: 11 },  q3: { target: 16,  achieved: 0 }, q4: { target: 18,  achieved: 0 } },
  { key: "funds",     label: "Fund Requests Reviewed",iconKey: "wallet",         iconBg: "bg-rose-100",    iconText: "text-rose-700",
    trend: [1, 1, 2, 2, 3, 3, 3, 3, 4, 3, 3, 3],
    monthly: { target: 4,  achieved: 3 },  q1: { target: 10,  achieved: 7 },   q2: { target: 10,  achieved: 4 },   q3: { target: 10,  achieved: 0 }, q4: { target: 10,  achieved: 0 } },
];

const startedPeriods: Record<PeriodKey, boolean> = {
  monthly: true,
  q1:      true,
  q2:      true,
  midYear: true,
  q3:      false,
  q4:      false,
  fy:      true,
};

// FY runs Oct → Sep. The cumulative ramp rises through the year; values track
// month 1..12 of the FY (Oct = month 1).
const trendByMonth: OperatingTargets["trend"] = [
  { label: "Oct", actual: 18,  target: 12 },
  { label: "Nov", actual: 30,  target: 24 },
  { label: "Dec", actual: 45,  target: 36 },
  { label: "Jan", actual: 50,  target: 48 },
  { label: "Feb", actual: 52,  target: 60 },
  { label: "Mar", actual: 55,  target: 72 },
  { label: "Apr", actual: 56,  target: 80 },
  { label: "May", actual: 56,  target: 86 },
  { label: "Jun", actual: 56,  target: 90 },
  { label: "Jul", actual: 56,  target: 94 },
  { label: "Aug", actual: 56,  target: 97 },
  { label: "Sep", actual: 56,  target: 100 },
];

export const cceoOperatingTargets: OperatingTargets = {
  scope:           "My Targets",
  audience:        "CCEO",
  fiscalYearLabel: "FY 2025/26",
  periodLabel:    "Nov 1 – Nov 30, 2025",
  lastUpdated:    "Nov 14, 2025 8:30 AM",
  daysCompleted:  { done: 21, total: 31 },
  startedPeriods,
  metrics:         cceoMetrics,
  trend:           trendByMonth,
  topFocus: [
    { rank: 1, label: "SSA Visits Completed",      detail: "57% achieved in Q2", status: "At Risk"  },
    { rank: 2, label: "Trainings Delivered",       detail: "54% achieved in Q2", status: "At Risk"  },
    { rank: 3, label: "Fund Requests Reviewed",    detail: "40% achieved in Q2", status: "Off Track" },
  ],
};

// ────────── PL personal scorecard ──────────
//
// PL targets are smaller-volume (they review + plan rather than do all
// the field work themselves). Same metric set, scaled appropriately.
const plMetrics: MetricRow[] = [
  { key: "schools",   label: "Schools Visited",        iconKey: "building2",      iconBg: "bg-blue-100",    iconText: "text-blue-700",
    trend: [12, 14, 15, 14, 16, 17, 18, 17, 19, 20, 21, 22],
    monthly: { target: 18, achieved: 13 }, q1: { target: 45,  achieved: 36 },  q2: { target: 45,  achieved: 28 },  q3: { target: 45,  achieved: 0 }, q4: { target: 48, achieved: 0 } },
  { key: "trainings", label: "Trainings Delivered",    iconKey: "graduationCap",  iconBg: "bg-emerald-100", iconText: "text-emerald-700",
    trend: [2, 3, 3, 4, 3, 4, 4, 4, 5, 4, 5, 5],
    monthly: { target: 6,  achieved: 4 },  q1: { target: 15,  achieved: 11 },  q2: { target: 15,  achieved: 9 },   q3: { target: 15,  achieved: 0 }, q4: { target: 18, achieved: 0 } },
  { key: "ssa",       label: "SSA Visits Completed",   iconKey: "activity",       iconBg: "bg-violet-100",  iconText: "text-violet-700",
    trend: [3, 4, 3, 5, 4, 4, 5, 4, 4, 5, 4, 5],
    monthly: { target: 8,  achieved: 5 },  q1: { target: 18,  achieved: 13 },  q2: { target: 20,  achieved: 12 },  q3: { target: 20,  achieved: 0 }, q4: { target: 22, achieved: 0 } },
  { key: "followups", label: "Follow-ups Closed",      iconKey: "checkCircle2",   iconBg: "bg-cyan-100",    iconText: "text-cyan-700",
    trend: [3, 4, 5, 5, 6, 6, 7, 7, 7, 8, 8, 8],
    monthly: { target: 10, achieved: 7 },  q1: { target: 22,  achieved: 17 },  q2: { target: 22,  achieved: 14 },  q3: { target: 22,  achieved: 0 }, q4: { target: 24, achieved: 0 } },
  { key: "plans",     label: "Plan Approvals",         iconKey: "clipboardCheck", iconBg: "bg-amber-100",   iconText: "text-amber-700",
    trend: [4, 5, 6, 6, 7, 8, 8, 8, 9, 9, 9, 9],
    monthly: { target: 12, achieved: 8 },  q1: { target: 28,  achieved: 21 },  q2: { target: 28,  achieved: 17 },  q3: { target: 28,  achieved: 0 }, q4: { target: 30, achieved: 0 } },
  { key: "funds",     label: "Fund Requests Reviewed", iconKey: "wallet",         iconBg: "bg-rose-100",    iconText: "text-rose-700",
    trend: [2, 2, 3, 3, 3, 4, 4, 4, 4, 5, 4, 4],
    monthly: { target: 6,  achieved: 4 },  q1: { target: 14,  achieved: 10 },  q2: { target: 14,  achieved: 7 },   q3: { target: 14,  achieved: 0 }, q4: { target: 14, achieved: 0 } },
];

export const plOperatingTargets: OperatingTargets = {
  scope:           "My Targets",
  audience:        "Country Program Lead",
  fiscalYearLabel: "FY 2025/26",
  periodLabel:    "Nov 1 – Nov 30, 2025",
  lastUpdated:    "Nov 14, 2025 8:30 AM",
  daysCompleted:  { done: 21, total: 31 },
  startedPeriods,
  metrics:         plMetrics,
  trend:           trendByMonth,
  topFocus: [
    { rank: 1, label: "SSA Visits Completed",     detail: "60% achieved in Q2", status: "At Risk"  },
    { rank: 2, label: "Trainings Delivered",      detail: "60% achieved in Q2", status: "At Risk"  },
    { rank: 3, label: "Fund Requests Reviewed",   detail: "50% achieved in Q2", status: "At Risk"  },
  ],
};

// ────────── Team aggregation ──────────
//
// "Team Targets" on PL / CD / HR / IA is just the sum of every CCEO's
// "My Targets" data multiplied by the team size we're surfacing. In
// production this would be a real SUM() over the per-staff target
// table; for the demo we synthesise a believable rollup that mirrors
// the design's status classifications.
const TEAM_CCEO_COUNT = 8;

export function teamOperatingTargets({
  scope,
  audience,
  size = TEAM_CCEO_COUNT,
}: {
  scope?:    string;
  audience?: string;
  size?:     number;
}): OperatingTargets {
  // Scale every CCEO row by team size, then apply a small per-row
  // dampening so the team rollup doesn't look like a perfect copy.
  const scale = (n: number, dampen = 1) => Math.round(n * size * dampen);
  const aggMetrics: MetricRow[] = cceoMetrics.map((m, idx) => {
    // dampen by 0.92..1.0 so each row has its own profile
    const d = 0.95 + ((idx % 3) * 0.025);
    return {
      ...m,
      trend: m.trend.map((v) => Math.round(v * size * d)),
      monthly: { target: scale(m.monthly.target),  achieved: scale(m.monthly.achieved, d) },
      q1:      { target: scale(m.q1.target),       achieved: scale(m.q1.achieved,      d) },
      q2:      { target: scale(m.q2.target),       achieved: scale(m.q2.achieved,      d) },
      q3:      { target: scale(m.q3.target),       achieved: scale(m.q3.achieved,      d) },
      q4:      { target: scale(m.q4.target),       achieved: scale(m.q4.achieved,      d) },
    };
  });
  return {
    scope:           scope    ?? "Team Targets",
    audience:        audience ?? "Country Program Lead",
    fiscalYearLabel: "FY 2025/26",
    periodLabel:    "Nov 1 – Nov 30, 2025",
    lastUpdated:    "Nov 14, 2025 8:30 AM",
    daysCompleted:  { done: 21, total: 31 },
    startedPeriods,
    metrics:         aggMetrics,
    trend:           trendByMonth,
    topFocus: [
      { rank: 1, label: "SSA Visits Completed",       detail: `${size} CCEOs · 57% achieved in Q2`, status: "At Risk"   },
      { rank: 2, label: "Trainings Delivered",         detail: `${size} CCEOs · 54% achieved in Q2`, status: "At Risk"   },
      { rank: 3, label: "Fund Requests Reviewed",      detail: `${size} CCEOs · 40% achieved in Q2`, status: "Off Track" },
    ],
  };
}
