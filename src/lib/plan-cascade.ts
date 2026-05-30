// Plan cascade — one field plan, three downstream views.
//
// The product rule: every planned activity is simultaneously
//   • a line of field work (the CCEO / Program Lead "My Plan"),
//   • a budget line (the Program Accountant's plan), and
//   • a record to be created and verified in Salesforce (the Impact
//     Assessment plan).
//
// So the Accountant and IA never build a plan by hand — theirs is
// DERIVED from the consolidated CCEO + PL field plan. This module is
// that derivation. All three views read from the same `plannedActivities`
// source so the numbers can never drift.

import {
  plannedActivities,
  planningHeader,
  type PlannedActivityRow,
  type AssignedTo,
} from "./planning-mock";

const PERIOD = planningHeader.filters.month; // e.g. "May 2025"

// Activities are grouped by who delivers them — the meaningful cut for
// both the field plan and the budget (partner-delivered work is a real,
// separately-funded channel).
const CHANNELS: AssignedTo[] = ["Me", "Cluster", "Partner", "Planned"];
const CHANNEL_LABEL: Record<AssignedTo, string> = {
  Me: "Staff-delivered",
  Cluster: "Cluster-delivered",
  Partner: "Partner-delivered",
  Planned: "Awaiting assignment",
};

function sum(rows: PlannedActivityRow[]): number {
  return rows.reduce((a, r) => a + r.estCost, 0);
}

export type ChannelSlice = {
  channel: string;
  count: number;
  cost: number;
  pct: number;
};

// Group a row set by delivery channel, dropping empty channels.
function channelSlices(rows: PlannedActivityRow[]): ChannelSlice[] {
  const total = sum(rows);
  return CHANNELS.map((c) => {
    const m = rows.filter((r) => r.assignedTo === c);
    const cost = sum(m);
    return {
      channel: CHANNEL_LABEL[c],
      count: m.length,
      cost,
      pct: total > 0 ? Math.round((cost / total) * 100) : 0,
    };
  }).filter((s) => s.count > 0);
}

// ────────── My Plan snapshot (CCEO / Program Lead) ──────────

export type MyPlanSnapshot = {
  period: string;
  schoolsCovered: number;
  autoBudget: number; // every activity's est cost — the budget this plan creates
};

export function monthlyPlanSnapshot(): MyPlanSnapshot {
  const rows = plannedActivities; // the consolidated monthly field plan
  return {
    period: PERIOD,
    schoolsCovered: new Set(rows.map((r) => r.schoolName)).size,
    autoBudget: sum(rows),
  };
}

// ────────── Periodized plan — Week / Month / Quarter / Year ──────────
//
// The CCEO / Program Lead "My Plan" target sheet: how many of each
// activity are planned across each horizon. Core schools follow the
// service package — 2 visits + 2 trainings per school per year, from
// staff, and the same again from partners.

export type PlanPeriod = "Week" | "Month" | "Quarter" | "Mid-Year" | "Year";
export const PLAN_PERIODS: readonly PlanPeriod[] = [
  "Week",
  "Month",
  "Quarter",
  "Mid-Year",
  "Year",
];

export type PlanLineGroup = "Field activities" | "Core schools";

export type PlanLineItem = {
  key: string;
  label: string;
  group: PlanLineGroup;
  byPeriod: Record<PlanPeriod, number>; // planned target per horizon
  actualByPeriod: Record<PlanPeriod, number>; // verified delivery per horizon
};

// Mid-Year is the half-year checkpoint. `actualByPeriod` is verified
// delivery measured against each horizon — the gap between the two is
// the pace. Exam-score collection is the standing laggard.
const planLines: PlanLineItem[] = [
  { key: "visits-staff",       group: "Field activities", label: "School visits — staff",
    byPeriod:       { Week: 16, Month: 64, Quarter: 190, "Mid-Year": 380, Year: 760 },
    actualByPeriod: { Week: 16, Month: 61, Quarter: 178, "Mid-Year": 360, Year: 712 } },
  { key: "visits-partner",     group: "Field activities", label: "School visits — partners",
    byPeriod:       { Week: 10, Month: 40, Quarter: 120, "Mid-Year": 240, Year: 480 },
    actualByPeriod: { Week: 9,  Month: 34, Quarter: 101, "Mid-Year": 205, Year: 408 } },
  { key: "ssa",                group: "Field activities", label: "SSA completions",
    byPeriod:       { Week: 6,  Month: 24, Quarter: 72,  "Mid-Year": 144, Year: 288 },
    actualByPeriod: { Week: 6,  Month: 25, Quarter: 75,  "Mid-Year": 150, Year: 300 } },
  { key: "cluster",            group: "Field activities", label: "Cluster meetings",
    byPeriod:       { Week: 2,  Month: 8,  Quarter: 24,  "Mid-Year": 48,  Year: 96  },
    actualByPeriod: { Week: 2,  Month: 8,  Quarter: 23,  "Mid-Year": 46,  Year: 93  } },
  { key: "exam",               group: "Core schools",     label: "Exam score collection",
    byPeriod:       { Week: 2,  Month: 8,  Quarter: 24,  "Mid-Year": 36,  Year: 72  },
    actualByPeriod: { Week: 1,  Month: 5,  Quarter: 16,  "Mid-Year": 25,  Year: 52  } },
  { key: "core-visit-staff",   group: "Core schools",     label: "Core visits — staff",
    byPeriod:       { Week: 1,  Month: 4,  Quarter: 12,  "Mid-Year": 24,  Year: 48  },
    actualByPeriod: { Week: 1,  Month: 4,  Quarter: 12,  "Mid-Year": 24,  Year: 47  } },
  { key: "core-train-staff",   group: "Core schools",     label: "Core trainings — staff",
    byPeriod:       { Week: 1,  Month: 4,  Quarter: 12,  "Mid-Year": 24,  Year: 48  },
    actualByPeriod: { Week: 1,  Month: 4,  Quarter: 11,  "Mid-Year": 21,  Year: 43  } },
  { key: "core-visit-partner", group: "Core schools",     label: "Core visits — partners",
    byPeriod:       { Week: 1,  Month: 4,  Quarter: 12,  "Mid-Year": 24,  Year: 48  },
    actualByPeriod: { Week: 1,  Month: 3,  Quarter: 10,  "Mid-Year": 20,  Year: 40  } },
  { key: "core-train-partner", group: "Core schools",     label: "Core trainings — partners",
    byPeriod:       { Week: 1,  Month: 4,  Quarter: 12,  "Mid-Year": 24,  Year: 48  },
    actualByPeriod: { Week: 1,  Month: 4,  Quarter: 13,  "Mid-Year": 26,  Year: 52  } },
];

// ────────── Pace + the operating view ──────────

export type PaceVerdict = "Ahead" | "On track" | "Behind";

function paceVerdict(pacePct: number): PaceVerdict {
  if (pacePct >= 100) return "Ahead";
  if (pacePct >= 88) return "On track";
  return "Behind";
}

const pacePct = (actual: number, planned: number) =>
  planned > 0 ? Math.round((actual / planned) * 100) : 0;

export type PlanLinePace = {
  key: string;
  label: string;
  group: PlanLineGroup;
  byPeriod: Record<PlanPeriod, number>;
  actualByPeriod: Record<PlanPeriod, number>;
  planned: number; // for the selected horizon
  actual: number; // for the selected horizon
  pacePct: number; // for the selected horizon
  verdict: PaceVerdict; // for the selected horizon
  forecastYear: number; // projected full-year delivery
};

export type PlanView = {
  period: PlanPeriod;
  lines: PlanLinePace[];
  periodPlanned: Record<PlanPeriod, number>; // planned total per horizon
  periodDelta: Record<PlanPeriod, number>; // +x% vs last cycle per horizon
  totalPlanned: number; // selected horizon
  totalActual: number; // selected horizon
  healthPct: number; // selected horizon
  verdict: PaceVerdict; // overall, selected horizon
  headline: string; // one derived sentence
  freshness: string;
};

// "+x% vs last cycle" shown on each horizon tile.
const PERIOD_DELTA: Record<PlanPeriod, number> = {
  Week: 6,
  Month: 9,
  Quarter: 12,
  "Mid-Year": 11,
  Year: 14,
};

export const planFreshness = "Synced with Salesforce · 4 min ago";

// The operating view for a chosen horizon — drives the My Plan card.
export function planView(period: PlanPeriod): PlanView {
  const lines: PlanLinePace[] = planLines.map((l) => {
    const planned = l.byPeriod[period];
    const actual = l.actualByPeriod[period];
    const p = pacePct(actual, planned);
    return {
      key: l.key,
      label: l.label,
      group: l.group,
      byPeriod: l.byPeriod,
      actualByPeriod: l.actualByPeriod,
      planned,
      actual,
      pacePct: p,
      verdict: paceVerdict(p),
      forecastYear: l.actualByPeriod.Year,
    };
  });
  const periodPlanned = Object.fromEntries(
    PLAN_PERIODS.map((p) => [
      p,
      planLines.reduce((a, l) => a + l.byPeriod[p], 0),
    ]),
  ) as Record<PlanPeriod, number>;
  const totalPlanned = periodPlanned[period];
  const totalActual = lines.reduce((a, l) => a + l.actual, 0);
  const healthPct = pacePct(totalActual, totalPlanned);
  const verdict = paceVerdict(healthPct);
  const worst = lines.reduce((w, l) => (l.pacePct < w.pacePct ? l : w));
  const headline =
    worst.pacePct < 88
      ? `${verdict} overall — ${worst.label} is ${Math.max(1, 100 - worst.pacePct)}% behind pace. Focus there.`
      : "Every activity is on or ahead of pace — hold the line.";
  return {
    period,
    lines,
    periodPlanned,
    periodDelta: PERIOD_DELTA,
    totalPlanned,
    totalActual,
    healthPct,
    verdict,
    headline,
    freshness: planFreshness,
  };
}

// ────────── Accountant's plan — auto-generated budget ──────────

export type BudgetLine = {
  category: string;
  amount: number;
  pct: number;
  activities: number;
};

export type AccountantDerivedPlan = {
  period: string;
  totalBudget: number;
  sourceActivities: number;
  schoolsCovered: number;
  lines: BudgetLine[]; // budget grouped by delivery channel
  awaitingApprovalCount: number;
  awaitingApprovalAmount: number;
  draftCount: number;
  draftAmount: number;
};

export function accountantDerivedPlan(): AccountantDerivedPlan {
  const rows = plannedActivities; // consolidated CCEO + PL field plan
  const awaiting = rows.filter((r) => r.status === "Submitted for Approval");
  const drafts = rows.filter((r) => r.status === "Draft");
  return {
    period: PERIOD,
    totalBudget: sum(rows),
    sourceActivities: rows.length,
    schoolsCovered: new Set(rows.map((r) => r.schoolName)).size,
    lines: channelSlices(rows)
      .map((s) => ({
        category: s.channel,
        amount: s.cost,
        pct: s.pct,
        activities: s.count,
      }))
      .sort((a, b) => b.amount - a.amount),
    awaitingApprovalCount: awaiting.length,
    awaitingApprovalAmount: sum(awaiting),
    draftCount: drafts.length,
    draftAmount: sum(drafts),
  };
}

// ────────── Impact Assessment's plan — auto-generated verification ──────────

export type VerificationLine = {
  intervention: string;
  records: number;
  schools: number;
};

export type IaDerivedPlan = {
  period: string;
  recordsExpected: number; // each planned activity → one Salesforce record
  schoolsToVerify: number;
  byIntervention: VerificationLine[];
  highPriorityRecords: number;
  partnerDeliveredRecords: number;
};

export function iaDerivedPlan(): IaDerivedPlan {
  const rows = plannedActivities; // consolidated CCEO + PL field plan
  const interventions = [...new Set(rows.map((r) => r.intervention))];
  const byIntervention: VerificationLine[] = interventions
    .map((intervention) => {
      const m = rows.filter((r) => r.intervention === intervention);
      return {
        intervention,
        records: m.length,
        schools: new Set(m.map((r) => r.schoolName)).size,
      };
    })
    .sort((a, b) => b.records - a.records);
  return {
    period: PERIOD,
    recordsExpected: rows.length,
    schoolsToVerify: new Set(rows.map((r) => r.schoolName)).size,
    byIntervention,
    highPriorityRecords: rows.filter((r) => r.priority === "High").length,
    partnerDeliveredRecords: rows.filter((r) => r.assignedTo === "Partner").length,
  };
}
