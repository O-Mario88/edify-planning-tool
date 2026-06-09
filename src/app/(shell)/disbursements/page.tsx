import { redirect } from "next/navigation";
import { StubPage } from "@/components/shell/StubPage";
import { AccountantQueueLive } from "@/components/funds/accountant/AccountantQueueLive";
import { getCurrentUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Field Fund Disbursement — LIVE. Role-locked to the Program Accountant (+ CD/
// Admin oversight). The queue is backend-driven (/api/activities/payment-queue)
// and the IA gate is enforced server-side: payment can never bypass verification.
export default async function DisbursementsPage() {
  const user = await getCurrentUser();
  const allowed = ["ProgramAccountant", "Admin", "CountryDirector"].includes(user.role);
  if (!allowed) redirect("/dashboards/program-lead");

  return (
    <StubPage
      title="Payments & Accountability"
      subtitle="Verified, IA-confirmed work ready to pay or clear. The system blocks any payment whose evidence, Salesforce ID, or IA confirmation is incomplete."
    >
      <AccountantQueueLive />
    </StubPage>
  );
}
