import { redirect } from "next/navigation";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DashboardGreetingHero } from "@/components/dashboards/DashboardGreetingHero";
import { AccountantConsoleDashboard } from "@/components/accountant-console/AccountantConsoleDashboard";
import { CommandStack } from "@/components/actions/CommandStack";
import { TodayCommandCenter } from "@/components/command/TodayCommandCenter";
import { AccountantPartnerPaymentsQueue } from "@/components/partner/AccountantPartnerPaymentsQueue";
import { PartnerPaymentQueue } from "@/components/payments/PartnerPaymentQueue";
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
  // Closed activities echo back the EXACT NetSuite Expense ID that closed them.
  const closedRows = activities()
    .filter((a) => a.status === "AccountabilityClosed" && a.netsuiteExpenseId)
    .map((a) => ({ id: a.id, title: a.title, netsuiteExpenseId: a.netsuiteExpenseId, assigneeName: a.assigneeId }));

  return (
    <>
      {/* Canonical page chrome — title + live role-scoped filters + search +
          message/notification/avatar cluster. Matches /dashboards/cceo. */}
      <DashboardPageHeader role="ProgramAccountant" />
      <div className="space-y-4 px-4 sm:px-5 md:px-6 pt-3 lg:pt-4 pb-24">
      {/* GREETING HERO — system-wide layout rule: header → hero → stats → work. */}
      <DashboardGreetingHero user={user} />
      {/* Payment pipeline — the statistics snapshot, directly below the
          hero: where money is stuck before the queues. */}
      <VerificationPaymentFunnel
        stages={ACCOUNTANT_PAYMENT_STAGES}
        title="Payment Pipeline"
        subtitle="IA verified → Sent to accountant → Cleared → Netsuite ID → Paid"
      />
      {/* WORK — today's queue, then the payment/accountability queues. */}
      <TodayCommandCenter />
      <CommandStack user={user} hideMission />
      {/* Partner-to-payment (backend, scoped, IA-gated). The live terminal
          gate: partner activities clear to paid only with evidence + SF ID +
          IA confirmation. Self-hides when the backend is disabled. */}
      <PartnerPaymentQueue />
      {/* Staff NetSuite Accountability — IA-confirmed activities to close. */}
      <StaffAccountabilityQueue rows={accountabilityRows} closed={closedRows} />
      {/* Partner Payments Ready to Clear — final leg of the partner
          workflow. Only PL-approved requests appear here (gate
          enforced in partner-workflow.REQUIRED_PATH). */}
      <AccountantPartnerPaymentsQueue />
      <AccountantConsoleDashboard />
      </div>
    </>
  );
}
