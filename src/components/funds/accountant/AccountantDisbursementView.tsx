"use client";

import { AccountantDisbursementHeader } from "./AccountantDisbursementHeader";
import { AccountantKpiRow } from "./AccountantKpiRow";
import { FundsReceivedPanel } from "./FundsReceivedPanel";
import { DisbursementQueue } from "./DisbursementQueue";
import { StaffBalanceTracker } from "./StaffBalanceTracker";
import { AccountabilityTracker } from "./AccountabilityTracker";
import { DisbursementHistory } from "./DisbursementHistory";
import { AuditTrailFeed } from "./AuditTrailFeed";
import { PlanScheduleByWeek } from "@/components/planning/PlanScheduleByWeek";
import { planItems, cceoPlanItems } from "@/lib/mobile-mock";

// Accountant — Field Fund Disbursement Command Center.
//
// Layout:
//   1. Header     — title + period chips + Export Ledger
//   2. KPI strip  — 6 finance KPIs
//   3. Row A      — Funds Received (4) + Disbursement Queue (8)
//   4. Row B      — Staff Balance (5) + Accountability Tracker (7)
//   5. Row C      — Disbursement History (7) + Audit Trail (5)
export function AccountantDisbursementView({
  iaPendingByStaff = {},
}: {
  iaPendingByStaff?: Record<string, number>;
}) {
  // Country-wide activity wave: PL + CCEO field plans combined. The
  // accountant uses this forward-looking view to time fund readiness
  // — each week's cost total is the cash that must clear by Monday
  // of that week. Production swaps this for a real query against all
  // approved plans in the accountant's country.
  const upcomingActivities = [...planItems, ...cceoPlanItems];

  return (
    <>
      <AccountantDisbursementHeader />
      <AccountantKpiRow />

      <div className="px-3 sm:px-4 lg:px-6 pb-3 space-y-3 lg:space-y-4">
        {/* Forward-looking activity wave. Sits above the disbursement
            queue because "what's coming" frames "what's in the queue
            today" — the accountant reads top-to-bottom from horizon
            to immediate. */}
        <PlanScheduleByWeek
          items={upcomingActivities}
          audience="finance"
          title="Upcoming activity wave — fund-need forecast"
          initialExpanded="first"
        />

        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-start">
          <div className="col-span-12 lg:col-span-4">
            <FundsReceivedPanel />
          </div>
          <div className="col-span-12 lg:col-span-8">
            <DisbursementQueue iaPendingByStaff={iaPendingByStaff} />
          </div>
        </section>

        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-start">
          <div className="col-span-12 lg:col-span-5">
            <StaffBalanceTracker />
          </div>
          <div className="col-span-12 lg:col-span-7">
            <AccountabilityTracker />
          </div>
        </section>

        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-start">
          <div className="col-span-12 lg:col-span-7">
            <DisbursementHistory />
          </div>
          <div className="col-span-12 lg:col-span-5">
            <AuditTrailFeed />
          </div>
        </section>
      </div>
    </>
  );
}
