import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { FundApprovalsHeader } from "@/components/approvals/FundApprovalsHeader";
import { FundApprovalsKpiRow } from "@/components/approvals/FundApprovalsKpiRow";
import { FundApprovalQueue } from "@/components/approvals/FundApprovalQueue";
import { FundApprovalQueueLive } from "@/components/funds/FundApprovalQueueLive";
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
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import {
  liveApprovalsForPl,
  liveApprovalsForAccountant,
  liveCdFundRequests,
} from "@/lib/funds/live-approval-queue";
import { getFilterScope } from "@/lib/filters/scope-service";
import { liveDistrictNamesFor } from "@/lib/api/surfaces";
import { selectionFromSearchParams, applyGeographyScope } from "@/lib/filters/apply-filters";

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

export default async function FundApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  // Live, URL-synced filter selection (the HeaderFilterBar writes it).
  const selection = selectionFromSearchParams(await searchParams);
  const liveDistrictNames = await liveDistrictNamesFor(user);
  const filterScope = getFilterScope({ user, liveDistrictNames });

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
    // Live CD-tier approval queue (non-CCEO requesters) from the action
    // store, scoped by the header region/district filter. Mirrors the
    // PL/Accountant live migration.
    const cdRequests = applyGeographyScope(liveCdFundRequests(), selection, {
      district: (r) => r.district,
    });
    return (
      <ResponsiveDashboard
        mobile={<CountryFundApprovalsView cdRequests={cdRequests} filterScope={filterScope} />}
        desktop={<CountryFundApprovalsView cdRequests={cdRequests} filterScope={filterScope} />}
      />
    );
  }

  // Live queue from the action store the server actions mutate. PL sees
  // their team's pending submissions + returns; Accountant sees
  // PL-approved requests across teams ready for disbursement.
  const rawQueue =
    user.role === "ProgramAccountant"
      ? liveApprovalsForAccountant()
      : liveApprovalsForPl(user.staffId);

  // Apply the header filter selection (region/district) to the queue —
  // region is backfilled from each row's district via the geography
  // source of truth. This is what makes the filter bar actually filter.
  const liveQueue = applyGeographyScope(rawQueue, selection, {
    district: (r) => r.district,
  });

  const approvalExportRows = liveQueue.map((f) => ({
    CCEO: f.cceoName, District: f.district, Region: f.region,
    Amount: f.amount, Status: f.status,
    Visits: f.counts.visits, Partners: f.counts.partners,
    Clusters: f.counts.clusters, Trainings: f.counts.trainings,
  }));

  const plBody = (
    <>
      <FundApprovalsHeader exportRows={approvalExportRows} filterScope={filterScope} />
      <FundApprovalsKpiRow />

      <div className="px-3 sm:px-4 lg:px-6 pb-3 space-y-3 lg:space-y-4">
        {/* Live fund-request approval queue (backend) — real submitted requests
            routed to this approver. The richer plan workbench below stays mock. */}
        <FundApprovalQueueLive canDisburse={user.role === "ProgramAccountant" || user.role === "Admin"} />

        {isMockAllowed() ? (
          <section className="grid grid-cols-12 gap-3 lg:gap-4 items-start">
            <div className="col-span-12 xl:col-span-7">
              <FundApprovalQueue queue={liveQueue} />
            </div>
            <div className="col-span-12 xl:col-span-5 flex flex-col gap-3 lg:gap-4">
              <div className="hidden xl:block">
                <FundPlanDetail queue={liveQueue} />
              </div>
              <ApprovalRulesCard />
            </div>
          </section>
        ) : (
          <InsufficientData
            surface="the legacy fund-approval workbench"
            detail="Submitted fund requests are approved in the live queue above. The detailed plan workbench is withheld until it reads from the backend."
          />
        )}

        {isMockAllowed() && (
          <>
            <FundApprovalsSummaryRow />
            <FundApprovalsFooter />
          </>
        )}
      </div>
    </>
  );

  return <ResponsiveDashboard mobile={plBody} desktop={plBody} />;
}
