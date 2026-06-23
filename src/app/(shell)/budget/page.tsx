import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { buildBudgetSummary } from "@/lib/funds/budget/budget-summary";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import { Wallet } from "lucide-react";
import { BudgetTemplateView } from "@/components/budget/template/BudgetTemplateView";
import { fetchBudgetBoard } from "@/lib/api/surfaces";

// Role-aware budget template — grouped activities by category, period lenses
// (weekly / monthly / quarterly / yearly), and summary KPIs. Scoped per role:
//   • CD / Accountant / IA → country
//   • RVP                  → consolidated country summary
//   • PL                   → team + own
//   • CCEO                 → own plan only
export default async function BudgetPage() {
  const user = await getCurrentUser();
  const role = user.role;

  if (["PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "HumanResource", "ProjectCoordinator"].includes(role)) {
    redirect(ROLE_REDIRECT[role]);
  }

  if (!isMockAllowed()) {
    const live = await fetchBudgetBoard(user);

    return (
      <>
        {live.live ? (
          <BudgetTemplateView data={live.data} role={role} />
        ) : (
          <ProductiveEmptyState
            Icon={Wallet}
            title="No budget to cost yet"
            description="The budget is computed from scheduled activities × the Country Cost Register. Schedule activities and set costs, and the budget builds itself."
            actionLabel={role === "CCEO" ? "Open My Plan" : "Open Planning"}
            actionHref={role === "CCEO" ? "/my-plan" : "/planning"}
            links={[
              { label: "Cost catalogue", href: "/cost-catalogue" },
              { label: "Fund requests", href: role === "CCEO" ? "/weekly-funds" : "/approvals" },
            ]}
            note="No fabricated money figures are shown — the budget reflects real scheduled activities only."
          />
        )}
      </>
    );
  }

  // Dev mock: still render the template shell with mock rollup figures when backend is off.
  const summary = buildBudgetSummary(role);
  const mockBoard = buildMockBoard(summary, role);
  let body: ReactNode = <BudgetTemplateView data={mockBoard} role={role} />;

  return (
    <>
      {body}
    </>
  );
}

function buildMockBoard(
  summary: ReturnType<typeof buildBudgetSummary>,
  role: string,
): Omit<import("@/lib/api/surfaces").BeBudgetBoard, "live"> {
  const r = summary.rollup;
  const total = r.approved || r.requested || 12_000_000;
  return {
    fy: "2026",
    role,
    scope: role === "RVP" || role === "CountryDirector" ? "country" : role === "CountryProgramLead" ? "team" : "own",
    viewMode: role === "RVP" ? "country_summary" : role === "CountryProgramLead" ? "team" : role === "CCEO" ? "own" : "country",
    lens: "month",
    lensLabel: "Jun FY2026",
    period: { month: 6, quarter: "Q3", week: 3 },
    summary: {
      thisWeek: Math.round(total * 0.04),
      nextWeek: Math.round(total * 0.05),
      thisMonth: Math.round(total / 10),
      thisQuarter: Math.round(total / 4),
      fiscalYear: total,
      periodTotal: Math.round(total / 10),
      activityCount: 42,
      costMissingCount: 0,
    },
    grouped: [
      {
        category: "School Visits",
        rows: [
          {
            index: 1,
            activity: "School Visits",
            schoolCount: 25,
            responsible: "Denis (CCEO)",
            unitCost: 56_000,
            total: 1_400_000,
            costMissing: false,
          },
          {
            index: 2,
            activity: "Follow Up Visit",
            schoolCount: 12,
            responsible: "Sarah (CCEO)",
            unitCost: 48_000,
            total: 576_000,
            costMissing: false,
          },
        ],
      },
      {
        category: "Training",
        rows: [
          {
            index: 3,
            activity: "Training",
            schoolCount: 180,
            responsible: "James (PL)",
            unitCost: 15_000,
            total: 2_700_000,
            costMissing: false,
          },
        ],
      },
    ],
    byCategory: [
      { label: "School Visits", amount: 1_976_000, pct: 42 },
      { label: "Training", amount: 2_700_000, pct: 58 },
    ],
    byMonth: r.byMonth.map((m, i) => ({ month: i + 1, label: m.label, amount: m.released, count: 3 })),
    workflow: [
      { step: 1, label: "Plan & cost from catalogue", detail: "Staff schedule activities; costs auto-calculated." },
      { step: 2, label: "CCEO → PL review", detail: "CCEO plans route to Program Lead." },
      { step: 3, label: "PL / IA / Accountant → CD", detail: "Other roles route to Country Director." },
      { step: 4, label: "CD approval + admin cost", detail: "CD adds administrative costs." },
      { step: 5, label: "RVP final approval", detail: "Country consolidation for RVP sign-off." },
    ],
  };
}
