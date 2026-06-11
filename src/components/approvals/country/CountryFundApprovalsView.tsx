"use client";

import { useState } from "react";
import { CountryFundApprovalsHeader } from "./CountryFundApprovalsHeader";
import { CountryFundFilterBar } from "./CountryFundFilterBar";
import { CountryFundKpiRow } from "./CountryFundKpiRow";
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
import type { WeeklyFundRequest } from "@/lib/funds/weekly-fund-types";

// Full Country Director Fund Approvals view — assembles the header,
// filter bar, KPI row, main 5/7 split (Queue + Plan Detail/Rules),
// 3-card summary row, and footer. Owns the open/closed state for the
// Create Admin Fund Request drawer. `cdRequests` is the live CD-tier
// queue (passed by the /approvals page); the action queue reads it.
export function CountryFundApprovalsView({ cdRequests }: { cdRequests?: WeeklyFundRequest[] } = {}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  return (
    <>
      <CountryFundApprovalsHeader onCreateRequest={() => setDrawerOpen(true)} />
      <CountryFundFilterBar />
      <CountryFundKpiRow />

      <div className="px-3 sm:px-4 lg:px-6 pb-3 space-y-3 lg:space-y-4">
        {/* Weekly fund approval queue — CD only approves higher-tier
            requesters (PL / IA / Accountant / SP / Admin). CCEO weekly
            requests stay with the Program Lead. Sits at the top so the
            inbox is the first thing the CD sees. */}
        <CdFundApprovalQueue requests={cdRequests} />

        {/* Main row — Queue (5) over Recent Activity, paired with
            Plan Detail (7) over Approval Rules. The Queue card is
            now content-sized (no h-full) so Recent Activity slots
            naturally beneath it in the same column, and the Budget
            Mix card below the summary row can finally take the full
            12-column width it needs to read clean. */}
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

        {/* Budget Mix — full row width. With Recent Activity moved
            into the left column above, the budget bar + 7-segment
            legend get the whole 12 columns to spread across. */}
        <CountryBudgetMixCard />
      </div>

      <CreateAdminFundRequestDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}
