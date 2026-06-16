import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { buildBudgetSummary } from "@/lib/funds/budget/budget-summary";
import { AnnualBudgetDashboard } from "@/components/budget/dashboards/AnnualBudgetDashboard";
import { RvpBudgetSummary } from "@/components/budget/dashboards/RvpBudgetSummary";
import { PlBudgetOverview } from "@/components/budget/dashboards/PlBudgetOverview";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Role-aware Budget page. The budget is the financial expression of the annual
// plan (generated from planned activities via the cost engine). Three views:
//   • CD / Accountant / IA / Admin → Annual Budget (full summary + detailed)
//   • RVP                          → RVP Budget Summary (summary-only)
//   • PL                           → PL Budget Overview (operational-only)
export default async function BudgetPage() {
  const user = await getCurrentUser();
  const role = user.role;
  // The annual budget dashboard is fabricated (UGX 116M program+admin with
  // invented requested/released/burn). Withhold money figures in production.
  if (!isMockAllowed()) return <InsufficientData surface="the annual budget" />;

  // CCEO sees a monthly own-plan slice elsewhere; partners have their own
  // surfaces — send them to their landing rather than the country budget.
  if (["CCEO", "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "HumanResource", "ProjectCoordinator"].includes(role)) {
    redirect(ROLE_REDIRECT[role]);
  }

  const summary = buildBudgetSummary(role);

  // Role-routed body. The big page-title rows that used to live inside each
  // dashboard were demoted to action-only toolbars — the canonical PageHeader
  // below owns the title so it isn't duplicated.
  let body: ReactNode;
  if (role === "RVP") {
    body = <RvpBudgetSummary rollup={summary.rollup} />;
  } else if (role === "CountryProgramLead") {
    body = <PlBudgetOverview rollup={summary.rollup} operational={summary.operational!} />;
  } else {
    // CountryDirector, ProgramAccountant, ImpactAssessment, Admin
    body = <AnnualBudgetDashboard rollup={summary.rollup} />;
  }

  return (
    <>
      {/* Canonical page chrome — title + search + identity cluster.
          PageHeader is a Client Component: pass only strings from this
          server page, never icon components. */}
      <PageHeader
        title="Annual Budget"
        subtitle="The financial expression of the annual plan — approved budgets, quarterly allocations, monthly burn, and fund requests."
      />
      {body}
    </>
  );
}
