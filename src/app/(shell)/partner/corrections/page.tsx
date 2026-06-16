// /partner/corrections — Corrections.
//
// Items returned by CCEO, PL, accountant, or M&E — live off the partner
// round-trip, filtered to activities whose evidence was rejected/returned (or
// whose status is "returned"). Each row links to the real evidence screen so
// the partner can re-upload corrected proof. When nothing is returned we show
// an honest empty state.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerActivityListLive } from "@/components/partner/PartnerActivityListLive";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerCorrectionsPage({
  searchParams,
}: {
  searchParams: Promise<{ preview?: string }>;
}) {
  const user = await getCurrentUser();
  const params = await searchParams;
  const previewMode = process.env.NODE_ENV !== "production" && params.preview === "1";
  if (!previewMode && !ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  return (
    <>
      <PartnerSubPageHeader
        title="Corrections"
        subtitle="Items returned by your CCEO, PL, or M&amp;E. Each row links straight to the evidence screen so you can re-upload corrected proof."
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12">
        {/* Live, backend-driven: only activities whose evidence was returned /
            rejected. Honest empty state when the queue is clean. */}
        <PartnerActivityListLive
          filter="corrections"
          variant="corrections"
          emptyHint="Nothing returned — your evidence is clean. Keep it up."
        />
      </div>
    </>
  );
}
