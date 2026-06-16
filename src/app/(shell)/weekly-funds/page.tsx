import { redirect } from "next/navigation";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { LeadWeeklyView } from "@/components/funds/lead/LeadWeeklyView";
import { StaffWeeklyView } from "@/components/funds/staff/StaffWeeklyView";
import { StaffAccountabilityLive } from "@/components/funds/staff/StaffAccountabilityLive";
import { AccountantDisbursementView } from "@/components/funds/accountant/AccountantDisbursementView";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Role-aware /weekly-funds.
//
//   • Program Lead / CD / Admin → LeadWeeklyView (approval queue)
//   • Program Accountant         → AccountantDisbursementView (disbursement)
//   • CCEO / staff               → StaffWeeklyView (their 4 weekly slips)
//   • Anyone else                → bounced to their dashboard
export default async function WeeklyFundsPage() {
  const user = await getCurrentUser();
  // Weekly fund totals/roster (Received 510M / Disbursed 284.5M) are fabricated;
  // money figures must never be shown as production data. Withhold until wired.
  if (!isMockAllowed()) return <InsufficientData surface="weekly funds" />;

  if (user.role === "ProgramAccountant") {
    return (
      <ResponsiveDashboard
        mobile={<AccountantDisbursementView />}
        desktop={<AccountantDisbursementView />}
      />
    );
  }

  if (
    user.role === "CountryProgramLead" ||
    user.role === "CountryDirector" ||
    user.role === "Admin"
  ) {
    return (
      <ResponsiveDashboard
        mobile={<LeadWeeklyView />}
        desktop={<LeadWeeklyView />}
      />
    );
  }

  if (user.role === "CCEO") {
    // Weekly slips (planning context) + the LIVE accountability close-out leg:
    // account for funds the accountant has disbursed (NetSuite Expense ID).
    const staffView = (
      <div className="space-y-4">
        <StaffWeeklyView staffId={user.staffId} staffName={user.name} />
        <StaffAccountabilityLive />
      </div>
    );
    return <ResponsiveDashboard mobile={staffView} desktop={staffView} />;
  }

  redirect("/dashboard");
}
