import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { EvidencePanel } from "@/components/evidence/EvidencePanel";
import { getCurrentUser } from "@/lib/auth";

// Per-activity evidence workspace — the real upload / preview / download /
// review surface for one activity. Reachable from My Plan + the evidence
// queues. Upload writes a real file to the backend; reviewers (CCEO/PL/IA/CD)
// can accept or return, which drives the IA + payment gate.
export const dynamic = "force-dynamic";

const REVIEWER_ROLES = new Set([
  "CCEO", "CountryProgramLead", "ImpactAssessment", "CountryDirector", "ProjectCoordinator", "Admin",
]);

export default async function ActivityEvidencePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const canReview = REVIEWER_ROLES.has(user.role);

  return (
    <StubPage
      title="Activity Evidence"
      subtitle="Upload proof of delivery, preview documents, and (for reviewers) accept or return evidence."
    >
      <div className="space-y-4">
        <Link href="/my-plan" className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--color-edify-primary)]">
          <ArrowLeft size={13} /> Back to My Plan
        </Link>
        <EvidencePanel activityId={id} canReview={canReview} />
      </div>
    </StubPage>
  );
}
