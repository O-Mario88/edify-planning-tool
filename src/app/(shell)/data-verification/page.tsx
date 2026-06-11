import { StubPage } from "@/components/shell/StubPage";
import { IaVerificationLive } from "@/components/impact/IaVerificationLive";
import { IaFundVerificationQueue } from "@/components/impact/IaFundVerificationQueue";
import { ClientVerificationCard } from "@/components/ssa/ClientVerificationCard";

// IA data verification — LIVE, backend-driven. Three queues:
//   1. Work waiting for IA confirmation (Salesforce IDs to confirm) →
//      /api/activities?status=awaiting_ia_verification + ia-confirm.
//   2. CCEO weekly fund requests awaiting the IA disbursement gate (B12).
//   3. The 10% client-portfolio SSA verification QA (already backend-live).
// No mock store — confirming here releases work to the accountant's queue.
export const dynamic = "force-dynamic";

export default function DataVerificationPage() {
  return (
    <StubPage
      title="IA Verification"
      subtitle="Confirm submitted work and SSA quality. Confirming a Salesforce ID releases the activity to the accountant for payment."
    >
      <IaVerificationLive />
      <IaFundVerificationQueue />
      <ClientVerificationCard />
    </StubPage>
  );
}
