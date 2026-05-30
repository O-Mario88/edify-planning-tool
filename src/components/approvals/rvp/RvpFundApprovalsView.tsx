"use client";

import { RvpFundApprovalsHeader } from "./RvpFundApprovalsHeader";
import { RvpKpiRow } from "./RvpKpiRow";
import { RvpCountryList } from "./RvpCountryList";
import { RvpCountryDetail } from "./RvpCountryDetail";
import { RvpDetailFooter } from "./RvpDetailFooter";
import { RvpCountryBudgetCard } from "@/components/funds/rvp/RvpCountryBudgetCard";

// RVP Fund Approval — full page assembly.
//
//   1. Header     — title + subtitle + FY/Quarter/Status + bell + Export
//   2. KPI row    — 6 tiles (Total · Pending · Approved · Countries · Avg Time · Utilization)
//   3. Main split — Country list (4) | Country detail (8)
//                   The detail card carries its own 5-KPI strip, tabs,
//                   Plan Summary + Spending by Category.
//   4. Footer     — Recent Fund Requests (7) + Approvals & Comments (5)
export function RvpFundApprovalsView() {
  return (
    <>
      <RvpFundApprovalsHeader />
      <RvpKpiRow />

      <div className="px-3 sm:px-4 lg:px-6 pb-3 space-y-3 lg:space-y-4">
        {/* Country Monthly Budget envelope approvals — RVP's only
            approval surface for individual money flows. Once approved,
            the country's weekly fund auto-generation activates. */}
        <RvpCountryBudgetCard />

        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-start">
          <div className="col-span-12 lg:col-span-4">
            <RvpCountryList />
          </div>
          <div className="col-span-12 lg:col-span-8 flex flex-col gap-3 lg:gap-4">
            <RvpCountryDetail />
            <RvpDetailFooter />
          </div>
        </section>
      </div>
    </>
  );
}
