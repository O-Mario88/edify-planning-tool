import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { FundApprovalsHeader } from "@/components/approvals/FundApprovalsHeader";
import { FundApprovalsFilterBar } from "@/components/approvals/FundApprovalsFilterBar";
import { FundApprovalsKpiRow } from "@/components/approvals/FundApprovalsKpiRow";
import { FundApprovalQueue } from "@/components/approvals/FundApprovalQueue";
import { FundPlanDetail } from "@/components/approvals/FundPlanDetail";
import {
  ApprovalRulesCard,
  FundApprovalsSummaryRow,
} from "@/components/approvals/FundApprovalsRightRail";
import { FundApprovalsFooter } from "@/components/approvals/FundApprovalsFooter";
import { CountryFundApprovalsView } from "@/components/approvals/country/CountryFundApprovalsView";
import { RvpFundApprovalsView } from "@/components/approvals/rvp/RvpFundApprovalsView";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";
import { redirect } from "next/navigation";
import { fundApprovalQueue } from "@/lib/fund-approvals-mock";

// Role-aware Approvals page.
//
// ACCESS CONTROL — only the four roles in the fund-flow chain can
// reach this page (CCEO + IA + HR + Partner are bounced):
//   • CountryProgramLead — approves team CCEO fund requests
//   • CountryDirector    — approves country-level requests
//   • RVP                — regional cross-country oversight
//   • ProgramAccountant  — clears disbursement, treasury intake
//   • Admin              — support
//
// Per-role view:
//   • Country Director / Admin → CD-scope view: country-level
//     queue across regions, CCEO contribution breakdown, country
//     plan & budget summary, Create Admin Fund Request drawer.
//   • RVP                → regional multi-country view (country picker
//     + plan + spending + recent requests + comments).
//   • Country Program Lead → PL-scope view: CCEO queue with team-level
//     approval flow, plan details for the selected CCEO, monthly
//     allocation snapshot.
//   • Program Accountant → falls through to the PL view (same queue
//     of approved-but-not-disbursed requests; the disbursement action
//     is what they own).
//
// Middleware in src/middleware.ts also gates `/approvals` to these
// roles; the redirect below is defense-in-depth for the case where a
// guard gap (unrouted edge case, bypass) lets a request through.
const ALLOWED: ReadonlySet<EdifyRole> = new Set([
  "CountryProgramLead",
  "CountryDirector",
  "RVP",
  "ProgramAccountant",
  "Admin",
]);

export default async function FundApprovalsPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }

  // RVP gets the multi-country regional view: country picker on the
  // left, country plan + spending + recent requests + comments on
  // the right. CD + Admin get the country-scope view (queue of teams
  // within a country). PL falls through to the team-scope view.
  if (user.role === "RVP") {
    return <ResponsiveDashboard mobile={<RvpFundApprovalsView />} desktop={<RvpFundApprovalsView />} />;
  }

  const isCountryScope =
    user.role === "CountryDirector" ||
    user.role === "Admin";

  if (isCountryScope) {
    return <ResponsiveDashboard mobile={<CountryFundApprovalsView />} desktop={<CountryFundApprovalsView />} />;
  }

  const plBody = (
    <>
      <FundApprovalsHeader />
      <FundApprovalsFilterBar />
      <FundApprovalsKpiRow />

      <div className="px-3 sm:px-4 lg:px-6 pb-3 space-y-3 lg:space-y-4">
        {/* Responsive layout for the approvals workbench:
            • Mobile + tablet (< xl): queue is full width and each row
              expands inline, so PLs/Accountants can review and act on
              a plan without losing scroll context.
            • Desktop (xl+): queue stays compact on the left (7/12) and
              the selected plan renders in its own card on the right
              (5/12) — clicking a row just highlights it; the side
              pane carries the funding breakdown + Approve / Return
              actions. ApprovalRulesCard docks below the detail. */}
        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-start">
          <div className="col-span-12 xl:col-span-7">
            <FundApprovalQueue queue={fundApprovalQueue} />
          </div>
          <div className="col-span-12 xl:col-span-5 flex flex-col gap-3 lg:gap-4">
            {/* Side detail pane — desktop only. Reads the same ?plan=
                URL key the queue writes, so clicking a row updates
                this pane. Hidden below xl since the queue handles its
                own inline expansion there. */}
            <div className="hidden xl:block">
              <FundPlanDetail queue={fundApprovalQueue} />
            </div>
            <ApprovalRulesCard />
          </div>
        </section>

        <FundApprovalsSummaryRow />
        <FundApprovalsFooter />
      </div>
    </>
  );

  return <ResponsiveDashboard mobile={plBody} desktop={plBody} />;
}
