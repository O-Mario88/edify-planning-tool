import { redirect } from "next/navigation";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { AccountantDisbursementView } from "@/components/funds/accountant/AccountantDisbursementView";
import { getCurrentUser } from "@/lib/auth";
import { activities } from "@/lib/actions/store";

export const dynamic = "force-dynamic";

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

  // IA-verification gate input: how many of each staffer's delivered
  // activities are still awaiting IA verification. The disbursement queue
  // blocks further advances to a staffer whose submitted work isn't yet
  // IA-verified — the general-queue analogue of the partner-cluster gate.
  const iaPendingByStaff: Record<string, number> = {};
  for (const a of activities()) {
    if (a.status === "SubmittedForVerification" && a.assigneeId) {
      iaPendingByStaff[a.assigneeId] = (iaPendingByStaff[a.assigneeId] ?? 0) + 1;
    }
  }

  return (
    <ResponsiveDashboard
      mobile={<AccountantDisbursementView iaPendingByStaff={iaPendingByStaff} />}
      desktop={<AccountantDisbursementView iaPendingByStaff={iaPendingByStaff} />}
    />
  );
}
