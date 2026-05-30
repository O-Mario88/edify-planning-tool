// Annual Budget Builder — the math layer behind the FY budget.
//
// Contract:
//   • Budget is GENERATED from: number of schools, school types, service rules,
//     planned activities, Core Package rules, Country Cost Settings.
//   • Every budget LINE traces back to the plan (formula + quantity + source).
//   • The Annual Budget breaks down into Quarterly → Monthly Funding Plans.
//   • Approval flow: Generated → Finance Review → CD Approval → (RVP) → Active.
//   • Variance review compares budgeted vs disbursed vs verified each month.
//   • Program Leads do NOT approve funds. They approve plans.

import "server-only";
import { activeFinancialYear } from "@/lib/fy-engine";
import { schoolsMock } from "@/lib/schools-mock";
import { activeCostFor } from "@/lib/cost-settings-mock";

// ────────── Models ──────────

export type BudgetCategory =
  | "School Improvement Training"
  | "SSA"
  | "SSA Verification"
  | "Cluster Training"
  | "In-School Coaching"
  | "School Visit"
  | "Core Visit"
  | "Core Training"
  | "Exam Result Collection"
  | "Enrollment Update"
  | "MSC Story"
  | "Special Project"
  | "Partner Activity";

export type BudgetSource =
  | "Service Rule"
  | "Recommendation Engine"
  | "Core Package Rule"
  | "Special Project Plan"
  | "Manual Approved Assumption";

export type BudgetStatus =
  | "Draft"
  | "Generated"
  | "Under Finance Review"
  | "Returned for Correction"
  | "Ready for CD Approval"
  | "Approved by CD"
  | "Submitted to RVP"
  | "Approved by RVP"
  | "Active"
  | "Archived";

export type AnnualBudgetLine = {
  id:              string;
  financialYearId: string;
  country:         string;
  region?:         string;
  district?:       string;
  cluster?:        string;
  budgetCategory:  BudgetCategory;
  quantity:        number;
  unitCost:        number;
  totalCost:       number;
  formula:         string;
  source:          BudgetSource;
  status:          BudgetStatus;
};

// ────────── Generation ──────────

const FY = activeFinancialYear();

// generateAnnualBudgetTemplate — derives line items from school counts +
// service rules + Country Cost Settings.
export function generateAnnualBudgetTemplate(fyId: string = FY.id): AnnualBudgetLine[] {
  const coreSchools   = schoolsMock.filter((s) => s.segment === "Core");
  const clientSchools = schoolsMock.filter((s) => s.segment === "Client");
  const newSchools    = schoolsMock.filter((s) => s.segment === "New");
  const activeSchools = schoolsMock.filter((s) => s.schoolStatus === "Active");

  const lines: AnnualBudgetLine[] = [];

  // ── Gateway: every active school gets one cluster training ──
  const clusterCount = Math.ceil(activeSchools.length / 12); // ~12 schools/cluster
  const clusterCost  = activeCostFor("Cluster training cost");
  lines.push(line({
    fyId,
    category: "School Improvement Training",
    quantity: clusterCount,
    unitCost: clusterCost,
    formula:  `${clusterCount} clusters × Cluster training cost`,
    source:   "Service Rule",
  }));

  // Meals at the cluster training (1 meal per school)
  const mealCost = activeCostFor("Participant meal cost");
  lines.push(line({
    fyId,
    category: "School Improvement Training",
    quantity: activeSchools.length,
    unitCost: mealCost,
    formula:  `${activeSchools.length} participants × Meal cost`,
    source:   "Service Rule",
  }));

  // ── SSA + SSA Verification: one per active school ──
  lines.push(line({
    fyId,
    category: "SSA",
    quantity: activeSchools.length,
    unitCost: activeCostFor("SSA support cost"),
    formula:  `${activeSchools.length} schools × SSA support cost`,
    source:   "Service Rule",
  }));
  lines.push(line({
    fyId,
    category: "SSA Verification",
    quantity: activeSchools.length,
    unitCost: activeCostFor("SSA verification cost"),
    formula:  `${activeSchools.length} schools × SSA verification cost`,
    source:   "Service Rule",
  }));

  // ── Core school package: 4 visits + 4 trainings each ──
  lines.push(line({
    fyId,
    category: "Core Visit",
    quantity: coreSchools.length * 4,
    unitCost: activeCostFor("Staff school visit cost"),
    formula:  `${coreSchools.length} Core × 4 visits × Staff visit cost`,
    source:   "Core Package Rule",
  }));
  lines.push(line({
    fyId,
    category: "Core Training",
    quantity: coreSchools.length * 4,
    unitCost: activeCostFor("In-School coaching cost"),
    formula:  `${coreSchools.length} Core × 4 trainings × Coaching cost`,
    source:   "Core Package Rule",
  }));

  // ── Client schools: 2 follow-up visits + 1 coaching ──
  lines.push(line({
    fyId,
    category: "School Visit",
    quantity: clientSchools.length * 2,
    unitCost: activeCostFor("Staff school visit cost"),
    formula:  `${clientSchools.length} Client × 2 visits × Staff visit cost`,
    source:   "Recommendation Engine",
  }));
  lines.push(line({
    fyId,
    category: "In-School Coaching",
    quantity: clientSchools.length,
    unitCost: activeCostFor("In-School coaching cost"),
    formula:  `${clientSchools.length} Client × 1 coaching × Coaching cost`,
    source:   "Recommendation Engine",
  }));

  // ── New school onboarding visits ──
  if (newSchools.length > 0) {
    lines.push(line({
      fyId,
      category: "School Visit",
      quantity: newSchools.length * 2,
      unitCost: activeCostFor("Staff school visit cost"),
      formula:  `${newSchools.length} New × 2 onboarding visits × Staff visit cost`,
      source:   "Service Rule",
    }));
  }

  // ── Annual ops: exam results, enrollment updates, MSC stories ──
  lines.push(line({
    fyId,
    category: "Exam Result Collection",
    quantity: activeSchools.length,
    unitCost: activeCostFor("Exam result collection cost"),
    formula:  `${activeSchools.length} schools × Exam result collection`,
    source:   "Service Rule",
  }));
  lines.push(line({
    fyId,
    category: "Enrollment Update",
    quantity: activeSchools.length,
    unitCost: activeCostFor("Enrollment update cost"),
    formula:  `${activeSchools.length} schools × Enrollment update`,
    source:   "Service Rule",
  }));
  lines.push(line({
    fyId,
    category: "MSC Story",
    quantity: Math.ceil(activeSchools.length * 0.4),
    unitCost: activeCostFor("MSC story collection cost"),
    formula:  `40% of active schools × MSC story`,
    source:   "Service Rule",
  }));

  // ── Partner activities (~30% of Core trainings are partner-led) ──
  const partnerTrainings = Math.ceil(coreSchools.length * 4 * 0.3);
  lines.push(line({
    fyId,
    category: "Partner Activity",
    quantity: partnerTrainings,
    unitCost: activeCostFor("Partner training fee"),
    formula:  `30% of Core trainings × Partner training fee`,
    source:   "Service Rule",
  }));

  // ── Special projects (fixed sessions) ──
  lines.push(line({
    fyId,
    category: "Special Project",
    quantity: 48,
    unitCost: activeCostFor("Special project session cost"),
    formula:  `48 sessions × Special project cost`,
    source:   "Special Project Plan",
  }));

  return lines;
}

let __nextLineSeq = 1;
function line({
  fyId, category, quantity, unitCost, formula, source,
}: {
  fyId: string;
  category: BudgetCategory;
  quantity: number;
  unitCost: number;
  formula: string;
  source: BudgetSource;
}): AnnualBudgetLine {
  return {
    id:              `bl-${fyId}-${__nextLineSeq++}`,
    financialYearId: fyId,
    country:         "Uganda",
    budgetCategory:  category,
    quantity,
    unitCost,
    totalCost:       quantity * unitCost,
    formula,
    source,
    status:          "Active",
  };
}

// Snapshot used by every budget page.
export const annualBudgetLines = generateAnnualBudgetTemplate();

export const annualBudgetTotal = annualBudgetLines.reduce(
  (a, l) => a + l.totalCost,
  0,
);

// ────────── Quarterly / Monthly breakdown ──────────

// breakAnnualBudgetIntoQuarterlyBudget — by default 25% each, but Q1 carries
// the cluster gateway weight so we tilt the distribution toward Q1.
const QUARTER_WEIGHTS = { Q1: 0.34, Q2: 0.22, Q3: 0.22, Q4: 0.22 } as const;

export function breakAnnualBudgetIntoQuarterlyBudget(
  lines: AnnualBudgetLine[] = annualBudgetLines,
): Record<"Q1" | "Q2" | "Q3" | "Q4", number> {
  const total = lines.reduce((a, l) => a + l.totalCost, 0);
  return {
    Q1: total * QUARTER_WEIGHTS.Q1,
    Q2: total * QUARTER_WEIGHTS.Q2,
    Q3: total * QUARTER_WEIGHTS.Q3,
    Q4: total * QUARTER_WEIGHTS.Q4,
  };
}

// FY-month order (Oct = 1).
const FY_MONTHS = [
  { key: "Oct", quarter: "Q1" }, { key: "Nov", quarter: "Q1" }, { key: "Dec", quarter: "Q1" },
  { key: "Jan", quarter: "Q2" }, { key: "Feb", quarter: "Q2" }, { key: "Mar", quarter: "Q2" },
  { key: "Apr", quarter: "Q3" }, { key: "May", quarter: "Q3" }, { key: "Jun", quarter: "Q3" },
  { key: "Jul", quarter: "Q4" }, { key: "Aug", quarter: "Q4" }, { key: "Sep", quarter: "Q4" },
] as const;

export type MonthlyFundingPlanRow = {
  month:     string;
  quarter:   "Q1" | "Q2" | "Q3" | "Q4";
  budgeted:  number;
  funded:    number;     // approved fund requests
  disbursed: number;     // released to staff
  spent:     number;     // receipts + verified work
  variance:  number;     // budgeted - spent
};

export function breakQuarterlyBudgetIntoMonthlyFundingPlans(): MonthlyFundingPlanRow[] {
  const q = breakAnnualBudgetIntoQuarterlyBudget();
  return FY_MONTHS.map((m, i) => {
    const qBudget = q[m.quarter];
    // Q1 tilts toward Oct (gateway month); other quarters spread evenly.
    const monthShare = m.quarter === "Q1"
      ? [0.55, 0.25, 0.20][i % 3]
      : 1 / 3;
    const budgeted = Math.round(qBudget * monthShare);
    // Demo state: months past or current have funding flowing; future months
    // are still budgeted-only.
    const monthsInFy = i + 1;
    const isPast = monthsInFy <= 2; // Oct, Nov are past for ENGINE_TODAY = 2025-11-15
    const funded    = isPast ? budgeted                      : Math.round(budgeted * 0.6);
    const disbursed = isPast ? Math.round(budgeted * 0.92)   : Math.round(budgeted * 0.40);
    const spent     = isPast ? Math.round(budgeted * 0.84)   : Math.round(budgeted * 0.28);
    return {
      month:    m.key,
      quarter:  m.quarter,
      budgeted,
      funded,
      disbursed,
      spent,
      variance: budgeted - spent,
    };
  });
}

export const monthlyFundingPlans = breakQuarterlyBudgetIntoMonthlyFundingPlans();

// calculateBudgetToPlanTraceability — for any line, show the school count,
// activity count, owner type, and monthly funding flow.
export function calculateBudgetToPlanTraceability(line: AnnualBudgetLine): {
  schoolCount?:    number;
  activityCount:   number;
  ownerType:       "Staff" | "Partner" | "Mixed";
  monthlyFunding:  number[];
} {
  const activityCount = line.quantity;
  const ownerType: "Staff" | "Partner" | "Mixed" =
    line.budgetCategory === "Partner Activity" ? "Partner" :
    line.budgetCategory === "Core Visit" || line.budgetCategory === "Core Training" ? "Mixed" :
    "Staff";
  const total = line.totalCost;
  // Roughly equal split into 12 months unless Q1-heavy category.
  const q1Heavy = line.budgetCategory === "School Improvement Training";
  const monthlyFunding = FY_MONTHS.map((m) => {
    if (q1Heavy && m.quarter === "Q1") return Math.round(total / 3);
    if (q1Heavy) return 0;
    return Math.round(total / 12);
  });
  return { activityCount, ownerType, monthlyFunding };
}

// calculateBudgetVariance — sum monthly funding plans.
export function calculateBudgetVariance(): {
  budgeted:  number;
  disbursed: number;
  spent:     number;
  variance:  number;
  pctSpent:  number;
} {
  const budgeted  = monthlyFundingPlans.reduce((a, m) => a + m.budgeted,  0);
  const disbursed = monthlyFundingPlans.reduce((a, m) => a + m.disbursed, 0);
  const spent     = monthlyFundingPlans.reduce((a, m) => a + m.spent,     0);
  return {
    budgeted,
    disbursed,
    spent,
    variance: budgeted - spent,
    pctSpent: budgeted === 0 ? 0 : Math.round((spent / budgeted) * 100),
  };
}

// ────────── Scenario planner ──────────

export type BudgetScenarioKey =
  | "minimum-coverage"
  | "standard"
  | "full-core-support"
  | "accelerated-catchup"
  | "partner-led-delivery"
  | "reduced-funding"
  | "expansion";

export type BudgetScenario = {
  key:               BudgetScenarioKey;
  label:             string;
  description:       string;
  totalCost:         number;
  schoolsCovered:    number;
  activitiesIncluded:string[];
  activitiesExcluded:string[];
  targetRisk:        "Low" | "Medium" | "High";
  fundingGap:        number;
  expectedImpact:    string;
};

// generateBudgetScenarios — produces the 7 named scenarios with computed
// totals so the CD/RVP can compare side by side.
export function generateBudgetScenarios(): BudgetScenario[] {
  const baseline = annualBudgetTotal;
  const activeSchools = schoolsMock.filter((s) => s.schoolStatus === "Active").length;
  const coreSchools   = schoolsMock.filter((s) => s.segment === "Core").length;
  return [
    {
      key: "minimum-coverage",
      label: "Minimum Coverage",
      description: "Gateway Training + SSA for every active school. No follow-up support.",
      totalCost: Math.round(baseline * 0.42),
      schoolsCovered: activeSchools,
      activitiesIncluded: ["School Improvement Training", "SSA", "SSA Verification"],
      activitiesExcluded: ["Core Visit", "Core Training", "Special Project", "MSC Story"],
      targetRisk: "High",
      fundingGap: Math.round(baseline * 0.58),
      expectedImpact: "Baseline only. No intervention follow-up; weak schools stay weak.",
    },
    {
      key: "standard",
      label: "Standard Annual Plan",
      description: "Gateway + SSA + recommended Client follow-up + Core package.",
      totalCost: baseline,
      schoolsCovered: activeSchools,
      activitiesIncluded: ["School Improvement Training", "SSA", "Client Follow-Up", "Core Package", "Annual Ops"],
      activitiesExcluded: ["Accelerated Catch-Up", "Expansion"],
      targetRisk: "Low",
      fundingGap: 0,
      expectedImpact: "On-plan for every active school. Core package fully delivered.",
    },
    {
      key: "full-core-support",
      label: "Full Core Support",
      description: "Standard plan + intensified Core Champion development + partner mentoring.",
      totalCost: Math.round(baseline * 1.18),
      schoolsCovered: activeSchools,
      activitiesIncluded: ["Standard plan", "Intensified Core mentoring", "Partner-led trainings"],
      activitiesExcluded: ["Expansion"],
      targetRisk: "Low",
      fundingGap: Math.round(baseline * 0.18),
      expectedImpact: "Stronger Core pipeline; 6+ Champion candidates ready by Year-End.",
    },
    {
      key: "accelerated-catchup",
      label: "Accelerated Catch-Up",
      description: "Standard plan + extra follow-up for High Risk / Critical staff and schools.",
      totalCost: Math.round(baseline * 1.12),
      schoolsCovered: activeSchools,
      activitiesIncluded: ["Standard plan", "Extra follow-up coaching", "Support-Review action plans"],
      activitiesExcluded: ["Special Project expansion"],
      targetRisk: "Medium",
      fundingGap: Math.round(baseline * 0.12),
      expectedImpact: "Mid-year recovery for under-performing staff and schools.",
    },
    {
      key: "partner-led-delivery",
      label: "Partner-Led Delivery",
      description: "Shift more activities to certified partners; lower staff load.",
      totalCost: Math.round(baseline * 1.07),
      schoolsCovered: activeSchools,
      activitiesIncluded: ["Standard plan", "Partner-led visits", "Partner-led trainings"],
      activitiesExcluded: ["Reduced staff load only"],
      targetRisk: "Medium",
      fundingGap: Math.round(baseline * 0.07),
      expectedImpact: "Faster delivery; partner quality must be monitored closely.",
    },
    {
      key: "reduced-funding",
      label: "Reduced Funding Scenario",
      description: "Standard plan minus 25% of partner trainings + MSC stories + special projects.",
      totalCost: Math.round(baseline * 0.78),
      schoolsCovered: activeSchools,
      activitiesIncluded: ["Gateway", "SSA", "Core visits"],
      activitiesExcluded: ["Most Partner trainings", "Most MSC stories", "Special Project"],
      targetRisk: "High",
      fundingGap: 0,
      expectedImpact: "Coverage holds; depth weakens. Champion pipeline at risk.",
    },
    {
      key: "expansion",
      label: "Expansion",
      description: "Standard plan + 30 new Client schools + 12 new Core candidates.",
      totalCost: Math.round(baseline * 1.34),
      schoolsCovered: activeSchools + 42,
      activitiesIncluded: ["Standard plan", "New onboarding visits", "Additional Core trainings"],
      activitiesExcluded: [],
      targetRisk: "Medium",
      fundingGap: Math.round(baseline * 0.34),
      expectedImpact: `${activeSchools + 42} schools reached. New ${coreSchools + 12} Core candidates.`,
    },
  ];
}

export const budgetScenarios = generateBudgetScenarios();
