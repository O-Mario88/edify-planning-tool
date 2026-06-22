"use client";

import { useState } from "react";
import { CountryFundApprovalsHeader } from "./CountryFundApprovalsHeader";
import { CountryFundKpiRow } from "./CountryFundKpiRow";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import type { FilterScope } from "@/lib/filters/types";
import { CountryFundQueue } from "./CountryFundQueue";
import { CountryFundPlanDetail } from "./CountryFundPlanDetail";
import {
  CountryApprovalRulesCard,
  CountryFundSummaryRow,
} from "./CountryFundSummary";
import {
  CountryBudgetMixCard,
  CountryRecentActivityCard,
} from "./CountryFundFooter";
import { CreateAdminFundRequestDrawer } from "./CreateAdminFundRequestDrawer";
import { CdFundApprovalQueue } from "@/components/funds/cd/CdFundApprovalQueue";
import { FundApprovalQueueLive } from "@/components/funds/FundApprovalQueueLive";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import type { WeeklyFundRequest } from "@/lib/funds/weekly-fund-types";

// Full Country Director Fund Approvals view — assembles the header,
// filter bar, KPI row, main 5/7 split (Queue + Plan Detail/Rules),
// 3-card summary row, and footer. Owns the open/closed state for the
// Create Admin Fund Request drawer. `cdRequests` is the live CD-tier
// queue (passed by the /approvals page); the action queue reads it.
export function CountryFundApprovalsView({
  cdRequests,
  filterScope,
}: {
  cdRequests?: WeeklyFundRequest[];
  filterScope?: FilterScope;
} = {}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const mockOk = isMockAllowed();
  const exportRows = (cdRequests ?? []).map((r) => ({
    Requester: r.staffName,
    Role: r.requesterRole ?? r.staffRole,
    District: r.district,
    Week: r.period.weekOfMonth,
    Month: r.period.monthLabel,
    Amount: r.requestedAmount.amount,
    Status: r.status,
  }));
  return (
    <>
      <CountryFundApprovalsHeader onCreateRequest={() => setDrawerOpen(true)} exportRows={exportRows} />
      {/* LIVE region/district filter (replaces the old static
          CountryFundFilterBar whose dropdowns + search did nothing).
          Scopes the CD queue via the same URL the page reads. */}
      {filterScope && (
        <div className="px-3 sm:px-4 lg:px-6 pt-1">
          <HeaderFilterBar scope={filterScope} />
        </div>
      )}
      <CountryFundKpiRow />

      <div className="px-3 sm:px-4 lg:px-6 pb-3 space-y-3 lg:space-y-4">
        {/* Weekly fund approval queue — CD only approves higher-tier
            requesters (PL / IA / Accountant / SP / Admin). CCEO weekly
            requests stay with the Program Lead. Sits at the top so the
            inbox is the first thing the CD sees. */}
        {mockOk ? (
          <CdFundApprovalQueue requests={cdRequests} />
        ) : (
          <FundApprovalQueueLive />
        )}

        {mockOk ? (
          <>
            <section className="grid grid-cols-12 gap-3 lg:gap-4 items-start">
              <div className="col-span-12 lg:col-span-5 flex flex-col gap-3 lg:gap-4">
                <CountryFundQueue />
                <CountryRecentActivityCard />
              </div>
              <div className="col-span-12 lg:col-span-7 flex flex-col gap-3 lg:gap-4">
                <CountryFundPlanDetail />
                <CountryApprovalRulesCard />
              </div>
            </section>

            <CountryFundSummaryRow />

            <CountryBudgetMixCard />
          </>
        ) : (
          <InsufficientData
            surface="the country fund-approval workbench"
            detail="Submitted fund requests are approved in the live queue above. Country plan detail and budget mix are withheld until wired to the backend."
          />
        )}
      </div>

      {mockOk && (
        <CreateAdminFundRequestDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      )}
    </>
  );
}
