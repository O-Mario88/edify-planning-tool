import { redirect } from "next/navigation";
import { AccountantConsoleDashboard } from "@/components/accountant-console/AccountantConsoleDashboard";
import { CommandStack } from "@/components/actions/CommandStack";
import { AccountantPartnerPaymentsQueue } from "@/components/partner/AccountantPartnerPaymentsQueue";
import { VerificationPaymentFunnel } from "@/components/cceo/VerificationPaymentFunnel";
import { StaffAccountabilityQueue } from "@/components/accountant-console/StaffAccountabilityQueue";
import type { CceoFunnelStage } from "@/lib/cceo-mock";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { activities } from "@/lib/actions/store";

// The finance leg of the workflow — where cleared money is on its way to
// paid. Largest stage-to-stage drop (here: Cleared → Netsuite ID) is the
// bottleneck the funnel calls out, matching the spec's Netsuite emphasis.
const ACCOUNTANT_PAYMENT_STAGES: CceoFunnelStage[] = [
  { key: "iaVerified",   label: "IA verified",         count: 18, href: "/approvals" },
  { key: "toAccountant", label: "Sent to accountant",  count: 15, href: "/disbursements" },
  { key: "cleared",      label: "Cleared",             count: 13, href: "/disbursements" },
  { key: "netsuite",     label: "Netsuite ID entered", count: 8,  href: "/disbursements" },
  { key: "paid",         label: "Paid",                count: 7,  href: "/disbursements" },
];

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
  // Phase 8: staff activities the IA has confirmed (status Verified) await
  // NetSuite accountability closure here — with the staff-entered Salesforce ID
  // as verified proof.
  const accountabilityRows = activities()
    .filter((a) => a.status === "Verified")
    .map((a) => ({ id: a.id, title: a.title, salesforceId: a.salesforceId, assigneeName: a.assigneeId }));

  return (
    <div className="space-y-4 px-4 sm:px-5 md:px-6 pt-4 pb-24">
      <CommandStack user={user} />
      {/* Staff NetSuite Accountability — IA-confirmed activities to close. */}
      <StaffAccountabilityQueue rows={accountabilityRows} />
      {/* Partner Payments Ready to Clear — final leg of the partner
          workflow. Only PL-approved requests appear here (gate
          enforced in partner-workflow.REQUIRED_PATH). */}
      <AccountantPartnerPaymentsQueue />
      {/* Payment pipeline — IA verified → accountant → cleared → Netsuite
          ID → paid. Surfaces where money is stuck before the queues. */}
      <VerificationPaymentFunnel
        stages={ACCOUNTANT_PAYMENT_STAGES}
        title="Payment Pipeline"
        subtitle="IA verified → Sent to accountant → Cleared → Netsuite ID → Paid"
      />
      <AccountantConsoleDashboard />
    </div>
  );
}
