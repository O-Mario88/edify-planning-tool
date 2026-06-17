import { redirect } from "next/navigation";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { LeadWeeklyView } from "@/components/funds/lead/LeadWeeklyView";
import { StaffWeeklyView } from "@/components/funds/staff/StaffWeeklyView";
import { StaffAccountabilityLive } from "@/components/funds/staff/StaffAccountabilityLive";
import { AccountantDisbursementView } from "@/components/funds/accountant/AccountantDisbursementView";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { PageHeader } from "@/components/ui/PageHeader";
import { LiveWeeklyFunds } from "@/components/funds/LiveWeeklyFunds";

// Role-aware /weekly-funds.
//
//   • Program Lead / CD / Admin → LeadWeeklyView (approval queue)
//   • Program Accountant         → AccountantDisbursementView (disbursement)
//   • CCEO / staff               → StaffWeeklyView (their 4 weekly slips)
//   • Anyone else                → bounced to their dashboard
export default async function WeeklyFundsPage() {
  const user = await getCurrentUser();
  // Production: LIVE weekly fund needs — aggregated by the backend from scheduled
  // activities × the CD cost register (/budget/weekly). Real money, role-scoped,
  // reconciles with the activity budget lines. Empty until activities are
  // scheduled. The fabricated roster views below render in dev mock mode only.
  if (!isMockAllowed()) {
    return (
      <>
        <PageHeader title="Weekly Funds" subtitle="Fund needs for the week, costed from scheduled activities via the Country Cost Register." />
        <div className="px-3 sm:px-4 md:px-5 pb-12 pt-3 space-y-4">
          <LiveWeeklyFunds />
          {user.role === "CCEO" && <StaffAccountabilityLive />}
        </div>
      </>
    );
  }

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
