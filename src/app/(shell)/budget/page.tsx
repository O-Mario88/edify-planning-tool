import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { buildBudgetSummary } from "@/lib/funds/budget/budget-summary";
import { AnnualBudgetDashboard } from "@/components/budget/dashboards/AnnualBudgetDashboard";
import { RvpBudgetSummary } from "@/components/budget/dashboards/RvpBudgetSummary";
import { PlBudgetOverview } from "@/components/budget/dashboards/PlBudgetOverview";

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

  const summary = buildBudgetSummary(role);

  if (role === "RVP") return <RvpBudgetSummary rollup={summary.rollup} />;
  if (role === "CountryProgramLead") return <PlBudgetOverview rollup={summary.rollup} operational={summary.operational!} />;
  // CountryDirector, ProgramAccountant, ImpactAssessment, Admin
  return <AnnualBudgetDashboard rollup={summary.rollup} />;
}
