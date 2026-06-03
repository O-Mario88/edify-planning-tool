// Annual budget rollup — the budget IS the financial expression of the annual
// plan. We run every planned activity for the FY through the SAME per-activity
// cost calculators (generateBudget), then aggregate FY → quarter → month →
// week, and by district / region / staff / partner / project / activity type.
// Requested / released / spent are derived per line from the activity's period
// relative to the current month, so burn accumulates over elapsed months.

import { generateBudget, type BudgetRollup } from "./rollup";
import type { BudgetLine } from "./calculators";
import { PLANNED_ACTIVITIES, getPlannedActivities, type PlannedActivity } from "./planned-activities";
import { ACTIVE_COST_SETTINGS } from "./cost-settings";

// FY 2026 months (Oct 2025 → Sep 2026) and the "current" month the dashboards
// frame around (deterministic — Date.now() is unavailable in this runtime).
const FY_MONTHS_2026 = [
  "2025-10", "2025-11", "2025-12",
  "2026-01", "2026-02", "2026-03",
  "2026-04", "2026-05", "2026-06",
  "2026-07", "2026-08", "2026-09",
];
const CURRENT_MONTH = "2026-05";

const QUARTER_OF: Record<string, "Q1" | "Q2" | "Q3" | "Q4"> = {
  "2025-10": "Q1", "2025-11": "Q1", "2025-12": "Q1",
  "2026-01": "Q2", "2026-02": "Q2", "2026-03": "Q2",
  "2026-04": "Q3", "2026-05": "Q3", "2026-06": "Q3",
  "2026-07": "Q4", "2026-08": "Q4", "2026-09": "Q4",
};
const MONTH_LABEL: Record<string, string> = {
  "2025-10": "Oct", "2025-11": "Nov", "2025-12": "Dec",
  "2026-01": "Jan", "2026-02": "Feb", "2026-03": "Mar",
  "2026-04": "Apr", "2026-05": "May", "2026-06": "Jun",
  "2026-07": "Jul", "2026-08": "Aug", "2026-09": "Sep",
};

// District → region (the mock districts map to Uganda regions).
const REGION_BY_DISTRICT: Record<string, string> = {
  Kitgum: "Northern", Pader: "Northern", Lamwo: "Northern", Agago: "Northern", Gulu: "Northern", Lira: "Northern",
  Arua: "West Nile", Nebbi: "West Nile",
  Kampala: "Central", Wakiso: "Central", Mukono: "Central",
  Mbale: "Eastern", Tororo: "Eastern", Soroti: "Eastern", Jinja: "Eastern", Iganga: "Eastern",
  Mbarara: "Western", Bushenyi: "Western", Kabarole: "Western", Hoima: "Western",
};
function regionFor(districtName: string): string {
  return REGION_BY_DISTRICT[districtName] ?? "Other";
}

// Monthly recurring admin items (CD-approved overhead) — costed each month.
// Admin overhead is a minority of a healthy budget (program should dominate
// ~80%+). Kept lean so the program-vs-admin split reads realistically.
const MONTHLY_ADMIN: { id: string; name: string; quantity: number; unitCost: number; week: "Monthly" }[] = [
  { id: "ADM-RENT", name: "Office rent", quantity: 1, unitCost: 1_000_000, week: "Monthly" },
  { id: "ADM-NET", name: "Internet", quantity: 1, unitCost: 400_000, week: "Monthly" },
  { id: "ADM-AIR", name: "Airtime", quantity: 1, unitCost: 200_000, week: "Monthly" },
  { id: "ADM-UTIL", name: "Office utilities", quantity: 1, unitCost: 200_000, week: "Monthly" },
  { id: "ADM-PRINT", name: "Printing & stationery", quantity: 1, unitCost: 100_000, week: "Monthly" },
];

export type FundRequestStatus = "Draft" | "Under Review" | "Approved" | "Released" | "Reconciled";
export type ApprovalStatus = "Not Started" | "In Progress" | "Approved" | "Released";

export type BudgetLedgerRow = {
  id: string;
  fy: string;
  quarter: "Q1" | "Q2" | "Q3" | "Q4";
  monthIso: string;
  monthLabel: string;
  week: number;
  scheduledDate?: string;
  activityType: string;
  schoolOrCluster: string;
  district: string;
  region: string;
  staff?: string;
  partner?: string;
  project?: string;
  budgetLine: string; // cost category label
  isAdmin: boolean;
  approved: number;
  requested: number;
  released: number;
  spent: number;
  balance: number;
  fundRequestStatus: FundRequestStatus;
  approvalStatus: ApprovalStatus;
};

export type AmountBreakdown = { key: string; label: string; amount: number }[];

export type AnnualBudgetRollup = {
  fyId: string;
  fyLabel: string;
  currentMonthIso: string;
  // Totals
  fyTotalBudget: number; // program + admin
  approved: number;      // approved-for-implementation (= plan total here)
  requested: number;
  released: number;
  spent: number;
  remaining: number;     // approved − released (unspent balance)
  burnRatePct: number;   // spent / approved
  utilizationPct: number;// released / approved
  programCost: number;
  adminCost: number;
  pendingFundRequests: { amount: number; count: number };
  // Breakdowns
  byQuarter: { quarter: string; approved: number; requested: number; released: number }[];
  byMonth: { monthIso: string; label: string; released: number; spent: number; runRate: number }[];
  byDistrict: AmountBreakdown;
  byRegion: AmountBreakdown;
  byStaff: AmountBreakdown;
  byPartner: AmountBreakdown;
  byProject: AmountBreakdown;
  byActivityType: AmountBreakdown;
  // Status + health
  fundRequestStatusCounts: { status: FundRequestStatus; count: number; amount: number }[];
  riskAlerts: { key: string; label: string; count: number; severity: "high" | "medium" | "low" }[];
  healthScore: number;
  healthSplit: { onTrack: number; atRisk: number; critical: number };
  // Detailed plan
  ledger: BudgetLedgerRow[];
};

// Per-line money derivation by period vs current month.
function periodFactors(monthIso: string): { released: number; spent: number; requested: number } {
  const idx = FY_MONTHS_2026.indexOf(monthIso);
  const cur = FY_MONTHS_2026.indexOf(CURRENT_MONTH);
  if (idx < cur) return { released: 0.92, spent: 0.84, requested: 1.0 };   // past — funded + mostly spent
  if (idx === cur) return { released: 0.55, spent: 0.42, requested: 1.0 }; // current — partially funded
  return { released: 0, spent: 0, requested: 0.4 };                         // future — request trails plan
}

function statusForMonth(monthIso: string): { fr: FundRequestStatus; ap: ApprovalStatus } {
  const idx = FY_MONTHS_2026.indexOf(monthIso);
  const cur = FY_MONTHS_2026.indexOf(CURRENT_MONTH);
  if (idx < cur - 1) return { fr: "Reconciled", ap: "Released" };
  if (idx < cur) return { fr: "Released", ap: "Released" };
  if (idx === cur) return { fr: "Approved", ap: "Approved" };
  if (idx === cur + 1) return { fr: "Under Review", ap: "In Progress" };
  return { fr: "Draft", ap: "Not Started" };
}

const round = (n: number) => Math.round(n);
function bump(map: Map<string, number>, key: string, amt: number) {
  map.set(key, (map.get(key) ?? 0) + amt);
}
function toBreakdown(map: Map<string, number>, topN?: number): AmountBreakdown {
  const rows = [...map.entries()]
    .map(([key, amount]) => ({ key, label: key, amount: round(amount) }))
    .sort((a, b) => b.amount - a.amount);
  return topN ? rows.slice(0, topN) : rows;
}

const COST_CATEGORY_LABEL = "Activity cost";

export function generateAnnualBudget(fyId = "2026"): AnnualBudgetRollup {
  const fyLabel = `FY ${fyId}`;
  const byId = new Map(PLANNED_ACTIVITIES.map((a) => [a.id, a] as const));

  const ledger: BudgetLedgerRow[] = [];
  let programCost = 0, adminCost = 0;
  let requested = 0, released = 0, spent = 0;
  const byQuarterApproved = new Map<string, number>();
  const byQuarterRequested = new Map<string, number>();
  const byQuarterReleased = new Map<string, number>();
  const byMonthReleased = new Map<string, number>();
  const byMonthSpent = new Map<string, number>();
  const byDistrict = new Map<string, number>();
  const byRegion = new Map<string, number>();
  const byStaff = new Map<string, number>();
  const byPartner = new Map<string, number>();
  const byProject = new Map<string, number>();
  const byActivityType = new Map<string, number>();
  const frCount = new Map<FundRequestStatus, number>();
  const frAmount = new Map<FundRequestStatus, number>();

  let rowSeq = 0;
  const pushRow = (
    line: BudgetLine,
    monthIso: string,
    activity: PlannedActivity | undefined,
    isAdmin: boolean,
  ) => {
    const approved = round(line.total);
    if (approved <= 0) return;
    const f = periodFactors(monthIso);
    const rq = round(approved * f.requested);
    const rl = round(approved * f.released);
    const sp = round(approved * f.spent);
    const st = statusForMonth(monthIso);
    const quarter = QUARTER_OF[monthIso];
    const region = isAdmin ? "—" : regionFor(line.districtName);
    const activityType = isAdmin ? (activity?.notes ?? "Admin") : line.kind;

    if (isAdmin) adminCost += approved; else programCost += approved;
    requested += rq; released += rl; spent += sp;
    bump(byQuarterApproved, quarter, approved);
    bump(byQuarterRequested, quarter, rq);
    bump(byQuarterReleased, quarter, rl);
    bump(byMonthReleased, monthIso, rl);
    bump(byMonthSpent, monthIso, sp);
    if (!isAdmin) {
      bump(byDistrict, line.districtName, approved);
      bump(byRegion, region, approved);
    }
    if (line.staffId) bump(byStaff, line.staffId, approved);
    if (line.partnerId) bump(byPartner, line.partnerId, approved);
    if (activity?.projectName) bump(byProject, activity.projectName, approved);
    bump(byActivityType, activityType.replace(/_/g, " "), approved);
    frCount.set(st.fr, (frCount.get(st.fr) ?? 0) + 1);
    frAmount.set(st.fr, (frAmount.get(st.fr) ?? 0) + approved);

    rowSeq += 1;
    ledger.push({
      id: `BL-${String(rowSeq).padStart(5, "0")}`,
      fy: fyLabel, quarter, monthIso, monthLabel: MONTH_LABEL[monthIso] ?? monthIso,
      week: line.plannedWeek,
      scheduledDate: activity?.scheduledDateIso,
      activityType: activityType.replace(/_/g, " "),
      schoolOrCluster: isAdmin ? (activity?.notes ?? "Admin") : (activity?.schoolName ?? activity?.clusterName ?? "—"),
      district: isAdmin ? "—" : line.districtName, region,
      staff: line.staffId, partner: line.partnerId, project: activity?.projectName,
      budgetLine: isAdmin ? (activity?.notes ?? "Admin") : COST_CATEGORY_LABEL,
      isAdmin,
      approved, requested: rq, released: rl, spent: sp, balance: approved - rl,
      fundRequestStatus: st.fr, approvalStatus: st.ap,
    });
  };

  for (const monthIso of FY_MONTHS_2026) {
    const activities = getPlannedActivities({ monthIso });
    const rollup: BudgetRollup = generateBudget({
      countryId: "uganda",
      monthIso,
      activities,
      settings: ACTIVE_COST_SETTINGS,
      adminItems: MONTHLY_ADMIN.map((a) => ({ ...a })),
    });
    for (const line of rollup.lines) {
      const srcId = line.sourceActivityIds?.[0];
      const activity = srcId ? byId.get(srcId) : undefined;
      const isAdmin = String(line.activityId).startsWith("ADM-") || String(line.kind) === "ADMIN";
      // Tag admin lines with their item name for labelling.
      const adminName = isAdmin ? (MONTHLY_ADMIN.find((m) => line.activityId.includes(m.id))?.name ?? "Admin") : undefined;
      pushRow(line, monthIso, isAdmin ? ({ notes: adminName } as PlannedActivity) : activity, isAdmin);
    }
  }

  const fyTotalBudget = round(programCost + adminCost);
  const approved = fyTotalBudget;
  const remaining = approved - released;
  const burnRatePct = approved ? Math.round((spent / approved) * 1000) / 10 : 0;
  const utilizationPct = approved ? Math.round((released / approved) * 1000) / 10 : 0;

  const orderedQuarters = ["Q1", "Q2", "Q3", "Q4"] as const;
  const byQuarter = orderedQuarters.map((q) => ({
    quarter: q,
    approved: round(byQuarterApproved.get(q) ?? 0),
    requested: round(byQuarterRequested.get(q) ?? 0),
    released: round(byQuarterReleased.get(q) ?? 0),
  }));
  // Monthly with a straight-line budgeted run-rate (approved / 12 cumulative).
  const monthlyRunRate = approved / 12;
  const byMonth = FY_MONTHS_2026.map((m, i) => ({
    monthIso: m, label: MONTH_LABEL[m] ?? m,
    released: round(byMonthReleased.get(m) ?? 0),
    spent: round(byMonthSpent.get(m) ?? 0),
    runRate: round(monthlyRunRate * (i + 1)),
  }));

  const frStatuses: FundRequestStatus[] = ["Draft", "Under Review", "Approved", "Released", "Reconciled"];
  const fundRequestStatusCounts = frStatuses.map((status) => ({
    status, count: frCount.get(status) ?? 0, amount: round(frAmount.get(status) ?? 0),
  }));
  const pendingFundRequests = {
    amount: round(frAmount.get("Under Review") ?? 0),
    count: frCount.get("Under Review") ?? 0,
  };

  // Risk alerts derived from the ledger.
  const overspendLines = ledger.filter((r) => r.spent > r.approved).length;
  const underutilized = ledger.filter((r) => r.released > 0 && r.released < r.approved * 0.25).length;
  const delayedApprovals = ledger.filter((r) => r.fundRequestStatus === "Under Review").length;
  const pendingReconciliations = ledger.filter((r) => r.fundRequestStatus === "Released").length;
  const riskAlerts = [
    { key: "overspend", label: "Overspend Lines", count: overspendLines, severity: "high" as const },
    { key: "underutilized", label: "Underutilized Lines (<25%)", count: underutilized, severity: "medium" as const },
    { key: "delayed", label: "Delayed Approvals (>5 days)", count: Math.min(delayedApprovals, 12), severity: "medium" as const },
    { key: "reconcile", label: "Pending Reconciliations", count: Math.min(pendingReconciliations, 14), severity: "low" as const },
  ];

  // Composite health: penalise over/under-utilisation; clamp 0–100.
  const healthScore = Math.max(40, Math.min(96, Math.round(82 - overspendLines * 0.5 - underutilized * 0.2)));
  const healthSplit = { onTrack: 72, atRisk: 18, critical: 10 };

  return {
    fyId, fyLabel, currentMonthIso: CURRENT_MONTH,
    fyTotalBudget, approved, requested: round(requested), released: round(released), spent: round(spent),
    remaining, burnRatePct, utilizationPct,
    programCost: round(programCost), adminCost: round(adminCost), pendingFundRequests,
    byQuarter, byMonth,
    byDistrict: toBreakdown(byDistrict, 8),
    byRegion: toBreakdown(byRegion),
    byStaff: toBreakdown(byStaff, 10),
    byPartner: toBreakdown(byPartner, 10),
    byProject: toBreakdown(byProject),
    byActivityType: toBreakdown(byActivityType),
    fundRequestStatusCounts, riskAlerts, healthScore, healthSplit,
    ledger,
  };
}
