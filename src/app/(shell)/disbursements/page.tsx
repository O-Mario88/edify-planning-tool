import { redirect } from "next/navigation";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { AccountantDisbursementView } from "@/components/funds/accountant/AccountantDisbursementView";
import { getCurrentUser } from "@/lib/auth";

// Field Fund Disbursement Command Center.
//
// Role-locked: only the Program Accountant (and Admin/CD for oversight)
// can reach this page. Everyone else gets bounced back to their
// dashboard via middleware-style server redirect.
export default async function DisbursementsPage() {
  const user = await getCurrentUser();
  const allowed = ["ProgramAccountant", "Admin", "CountryDirector"].includes(user.role);
  if (!allowed) {
    redirect("/dashboards/program-lead");
  }

  return (
    <ResponsiveDashboard
      mobile={<AccountantDisbursementView />}
      desktop={<AccountantDisbursementView />}
    />
  );
}
