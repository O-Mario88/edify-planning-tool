import { redirect } from "next/navigation";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { LeadWeeklyView } from "@/components/funds/lead/LeadWeeklyView";
import { StaffWeeklyView } from "@/components/funds/staff/StaffWeeklyView";
import { AccountantDisbursementView } from "@/components/funds/accountant/AccountantDisbursementView";
import { getCurrentUser } from "@/lib/auth";

// Role-aware /weekly-funds.
//
//   • Program Lead / CD / Admin → LeadWeeklyView (approval queue)
//   • Program Accountant         → AccountantDisbursementView (disbursement)
//   • CCEO / staff               → StaffWeeklyView (their 4 weekly slips)
//   • Anyone else                → bounced to their dashboard
export default async function WeeklyFundsPage() {
  const user = await getCurrentUser();

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
    return (
      <ResponsiveDashboard
        mobile={<StaffWeeklyView staffId={user.staffId} staffName={user.name} />}
        desktop={<StaffWeeklyView staffId={user.staffId} staffName={user.name} />}
      />
    );
  }

  redirect("/dashboard");
}
