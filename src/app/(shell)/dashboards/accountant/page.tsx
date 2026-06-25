import { redirect } from "next/navigation";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DashboardGreetingHero } from "@/components/dashboards/DashboardGreetingHero";
import { BudgetIntelligenceEmbed } from "@/components/budget/BudgetIntelligenceEmbed";
import { SectionBoundary } from "@/components/ui/SectionBoundary";
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
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { activities, fundRequests, disbursements } from "@/lib/actions/store";

// The finance leg of the workflow — where cleared money is on its way to
// paid. Counts come from the live store: activity statuses (Verified,
// AccountabilityClosed) feed the IA-verified/Paid ends, fund requests
// feed the cleared/sent stages, disbursements feed the actually-disbursed
// stage. Largest stage-to-stage drop is the bottleneck.
function paymentPipelineStages(): CceoFunnelStage[] {
  const acts = activities();
  const reqs = fundRequests();
  const disb = disbursements();
  const iaVerified   = acts.filter((a) => a.status === "Verified").length;
  const toAccountant = reqs.filter((r) => r.status === "APPROVED" || r.status === "READY_TO_DISBURSE").length;
  const cleared      = reqs.filter((r) => r.status === "DISBURSED" || r.status === "RECEIVED").length;
  const netsuite     = acts.filter((a) => a.status === "AccountabilityClosed" && !!a.netsuiteExpenseId).length;
  const paid         = disb.length;
  return [
    { key: "iaVerified",   label: "IA verified",         count: iaVerified,   href: "/approvals" },
    { key: "toAccountant", label: "Sent to accountant",  count: toAccountant, href: "/disbursements" },
    { key: "cleared",      label: "Cleared",             count: cleared,      href: "/disbursements" },
    { key: "netsuite",     label: "Netsuite ID entered", count: netsuite,     href: "/disbursements" },
    { key: "paid",         label: "Paid",                count: paid,         href: "/disbursements" },
  ];
}

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
  // The payment funnel (store-derived), the staff-accountability queue, and the
  // AccountantConsoleDashboard read hand-mocked finance fixtures
  // (@/lib/accountant-console-mock) — disbursement summaries, funds-received
  // tables, budget approvals. NEVER show fabricated money in production: gate
  // them behind isMockAllowed. The live BudgetIntelligenceEmbed, today queue,
  // and the backend-wired partner-payment queues below stay.
  const mockOk = isMockAllowed();
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

      {/* Budget Intelligence — finance-execution view: low-yield spend, spend at risk. */}
      <SectionBoundary label="budget intelligence">
        <BudgetIntelligenceEmbed heading="Budget Intelligence" />
      </SectionBoundary>
      {/* Payment pipeline — the statistics snapshot, directly below the
          hero: where money is stuck before the queues. Store-derived; mock-gated. */}
      {mockOk && (
        <VerificationPaymentFunnel
          stages={paymentPipelineStages()}
          title="Payment Pipeline"
          subtitle="IA verified → Sent to accountant → Cleared → Netsuite ID → Paid"
        />
      )}
      {/* WORK — today's queue, then the payment/accountability queues. */}
      <TodayCommandCenter />
      <CommandStack user={user} hideMission />
      {/* Partner-to-payment (backend, scoped, IA-gated). The live terminal
          gate: partner activities clear to paid only with evidence + SF ID +
          IA confirmation. Self-hides when the backend is disabled. */}
      <PartnerPaymentQueue />
      {/* Staff NetSuite Accountability — IA-confirmed activities to close.
          Store-derived; mock-gated. */}
      {mockOk && <StaffAccountabilityQueue rows={accountabilityRows} closed={closedRows} />}
      {/* Partner Payments Ready to Clear — final leg of the partner
          workflow. Only PL-approved requests appear here (gate
          enforced in partner-workflow.REQUIRED_PATH). */}
      <AccountantPartnerPaymentsQueue />
      {/* Accountant console — disbursement summaries, funds-received, budget
          approvals. Hand-mocked finance fixtures: withheld in production. */}
      {mockOk ? (
        <AccountantConsoleDashboard />
      ) : (
        <InsufficientData surface="the accountant finance console" detail="Disbursement summaries, funds-received tables, and budget approvals are withheld until the finance backend is wired — no fabricated money figures are shown. The Budget Intelligence and partner-payment queues above are live." />
      )}
      </div>
    </>
  );
}
