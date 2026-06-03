// Role-scoped budget summary. The annual rollup is the single source of truth;
// this decides which slice each role sees:
//   • CD / Accountant / IA → full (program + admin, all breakdowns, ledger)
//   • RVP                  → summary only (no raw activity ledger)
//   • PL                   → operational only (excludes admin/overhead) +
//                            budget-mix-by-source (CCEO / PL / Special projects)

import { generateAnnualBudget, type AnnualBudgetRollup, type AmountBreakdown } from "./annual-rollup";

export type BudgetView = "full" | "summary" | "operational";

export function budgetViewForRole(role: string): BudgetView {
  if (role === "RVP") return "summary";
  if (role === "CountryProgramLead") return "operational";
  // CCEO sees their own monthly slice elsewhere; default the budget page to full
  // for the finance/leadership roles that share the Annual Budget dashboard.
  return "full";
}

export type OperationalTotals = {
  approved: number;
  requested: number;
  released: number;
  spent: number;
  remaining: number;
  utilizationPct: number;
  burnRatePct: number;
  mixBySource: AmountBreakdown; // CCEO Plans / PL Plans / Special Projects
};

const STAFF_VISIT_KINDS = new Set([
  "staff visit", "follow up visit", "coaching visit", "ssa visit", "core visit",
]);

/** Operational (program-only) view for the PL: drop admin lines and split the
 *  program spend into CCEO plans / PL plans / Special projects. */
export function operationalTotals(rollup: AnnualBudgetRollup): OperationalTotals {
  const rows = rollup.ledger.filter((r) => !r.isAdmin);
  const sum = (sel: (r: (typeof rows)[number]) => number) => rows.reduce((a, r) => a + sel(r), 0);
  const approved = sum((r) => r.approved);
  const released = sum((r) => r.released);
  const spent = sum((r) => r.spent);
  const requested = sum((r) => r.requested);

  let ccceo = 0, pl = 0, project = 0;
  for (const r of rows) {
    if (r.project) project += r.approved;
    else if (STAFF_VISIT_KINDS.has(r.activityType)) ccceo += r.approved;
    else pl += r.approved; // trainings, cluster meetings, partner-led → PL plans
  }
  const mixBySource: AmountBreakdown = [
    { key: "cceo", label: "CCEO Plans", amount: Math.round(ccceo) },
    { key: "pl", label: "PL Plans", amount: Math.round(pl) },
    { key: "project", label: "Special Projects", amount: Math.round(project) },
  ];

  return {
    approved, requested, released, spent,
    remaining: approved - released,
    utilizationPct: approved ? Math.round((released / approved) * 1000) / 10 : 0,
    burnRatePct: approved ? Math.round((spent / approved) * 1000) / 10 : 0,
    mixBySource,
  };
}

export type RoleBudgetSummary = {
  view: BudgetView;
  fyId: string;
  rollup: AnnualBudgetRollup;
  operational?: OperationalTotals; // present for the PL view
};

export function buildBudgetSummary(role: string, fyId = "2026"): RoleBudgetSummary {
  const view = budgetViewForRole(role);
  const rollup = generateAnnualBudget(fyId);
  return {
    view, fyId, rollup,
    operational: view === "operational" ? operationalTotals(rollup) : undefined,
  };
}
