import { redirect } from "next/navigation";
import { AccountantConsoleDashboard } from "@/components/accountant-console/AccountantConsoleDashboard";
import { CommandStack } from "@/components/actions/CommandStack";
import { AccountantPartnerPaymentsQueue } from "@/components/partner/AccountantPartnerPaymentsQueue";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";

// /dashboards/accountant — Program Accountant Console.
//
// Role-locked: only the Program Accountant + Admin can land here.
// Everyone else gets bounced to their own dashboard.
export default async function AccountantConsolePage() {
  const user = await getCurrentUser();
  const allowed = ["ProgramAccountant", "Admin"].includes(user.role);
  if (!allowed) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  return (
    <div className="space-y-4 px-4 sm:px-5 md:px-6 pt-4 pb-24">
      <CommandStack user={user} />
      {/* Partner Payments Ready to Clear — final leg of the partner
          workflow. Only PL-approved requests appear here (gate
          enforced in partner-workflow.REQUIRED_PATH). */}
      <AccountantPartnerPaymentsQueue />
      <AccountantConsoleDashboard />
    </div>
  );
}
