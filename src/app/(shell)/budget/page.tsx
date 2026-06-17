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
import { LiveBudgetView } from "@/components/budget/LiveBudgetView";
import { fetchBudgetFromSchedule } from "@/lib/api/surfaces";

// Role-aware Budget page. The budget is the financial expression of the annual
// plan (generated from planned activities via the cost engine). Three views:
//   • CD / Accountant / IA / Admin → Annual Budget (full summary + detailed)
//   • RVP                          → RVP Budget Summary (summary-only)
//   • PL                           → PL Budget Overview (operational-only)
export default async function BudgetPage() {
  const user = await getCurrentUser();
  const role = user.role;

  // CCEO sees a monthly own-plan slice elsewhere; partners have their own
  // surfaces — send them to their landing rather than the country budget.
  if (["CCEO", "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "HumanResource", "ProjectCoordinator"].includes(role)) {
    redirect(ROLE_REDIRECT[role]);
  }

  // Production: LIVE budget — computed by the backend from scheduled activities ×
  // the CD cost register (real money, role-scoped). The rich mock dashboards
  // below render only in dev mock mode.
  if (!isMockAllowed()) {
    const live = await fetchBudgetFromSchedule(user);
    return (
      <>
        <PageHeader title="Annual Budget" subtitle="The financial expression of the annual plan — costed from scheduled activities via the Country Cost Register." />
        {live.live ? <LiveBudgetView b={live.data} /> : <InsufficientData surface="the annual budget" />}
      </>
    );
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
