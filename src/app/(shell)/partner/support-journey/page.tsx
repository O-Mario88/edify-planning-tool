// /partner/support-journey — Support Journey.
//
// Surfaces the school-improvement story: every assigned school's
// progression through Need → Assigned → Scheduled → Delivered →
// Evidence → CCEO → M&E → Improvement. Keeps the partner focused on
// what changes for the school, not just what gets paid.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerSupportJourneyList } from "@/components/partner/PartnerSupportJourneyList";
import { SchoolPartnerJourney, sampleJourneyForHope } from "@/components/partner/SchoolPartnerJourney";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerSupportJourneyPage({
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
        title="Support Journey"
        subtitle="Need → Partner assigned → Scheduled → Delivered → Evidence → CCEO → M&amp;E → Improvement. The story your work is writing in every school."
        kpis={[
          { label: "Schools supported",      value: 18, iconKey: "building",  tone: "neutral", caption: "This Month" },
          { label: "CCEO confirmed",         value: 11, iconKey: "shield",    tone: "good",    caption: "61% of supported" },
          { label: "M&E verified",           value: 7,  iconKey: "checks",    tone: "good",    caption: "39% of supported" },
          { label: "Moved up a band",        value: 2,  iconKey: "trending",  tone: "good",    caption: "Improvement detected" },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        <PartnerSupportJourneyList />

        {/* Featured journey — the canonical example (Hope Primary)
            so the partner can read what a complete timeline looks
            like at a glance. */}
        <SchoolPartnerJourney {...sampleJourneyForHope()} />
      </div>
    </>
  );
}
