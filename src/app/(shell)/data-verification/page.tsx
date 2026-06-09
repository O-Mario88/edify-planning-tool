import { StubPage } from "@/components/shell/StubPage";
import { IaVerificationLive } from "@/components/impact/IaVerificationLive";
import { ClientVerificationCard } from "@/components/ssa/ClientVerificationCard";

// IA data verification — LIVE, backend-driven. Two queues:
//   1. Work waiting for IA confirmation (Salesforce IDs to confirm) →
//      /api/activities?status=awaiting_ia_verification + ia-confirm.
//   2. The 10% client-portfolio SSA verification QA (already backend-live).
// No mock store — confirming here releases work to the accountant's queue.
export const dynamic = "force-dynamic";

export default function DataVerificationPage() {
  return (
    <StubPage
      title="IA Verification"
      subtitle="Confirm submitted work and SSA quality. Confirming a Salesforce ID releases the activity to the accountant for payment."
    >
      <IaVerificationLive />
      <ClientVerificationCard />
    </StubPage>
  );
}
