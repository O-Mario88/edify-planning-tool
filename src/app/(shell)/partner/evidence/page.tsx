// /partner/evidence — Evidence.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerEvidenceRequired } from "@/components/partner/PartnerEvidenceRequired";
import { PartnerEvidenceQualityPanel } from "@/components/partner/PartnerEvidenceQualityPanel";
import { EvidenceBulkDropzone, type EligibleActivity } from "@/components/partner/EvidenceBulkDropzone";
import { partnerActivities } from "@/lib/actions/store";

export const dynamic = "force-dynamic";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerEvidencePage({
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
  // Activities the current partner has marked Delivered are the ones
  // eligible for evidence upload. In mock-mode we surface anything in
  // Delivered status; production filters by partnerId === user.partnerId.
  const eligible: EligibleActivity[] = partnerActivities()
    .filter((a) => a.status === "Delivered")
    .map((a) => ({ id: a.id, title: a.title, schoolId: a.schoolId }));
  return (
    <>
      <PartnerSubPageHeader
        title="Evidence"
        subtitle="Upload what proves the right support happened at the right school. Evidence is the bridge to CCEO confirmation, PL approval, and payment."
        filters={[
          { iconKey: "calendar", label: "Last 30 days" },
          { iconKey: "filter",   label: "All activity types" },
        ]}
        kpis={[
          { label: "Completion rate", value: "91%",      iconKey: "upload", tone: "good", caption: "Required items uploaded" },
          { label: "Returned rate",   value: "6%",       iconKey: "rotate", tone: "warn", caption: "Of submissions"          },
          { label: "Avg correction",  value: "1.4 days", iconKey: "clock",  tone: "warn", caption: "Median fix turnaround"   },
          { label: "M&E verified",    value: "88%",      iconKey: "shield", tone: "good", caption: "Of confirmed activities" },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        <EvidenceBulkDropzone eligibleActivities={eligible} />
        <PartnerEvidenceRequired />
        <PartnerEvidenceQualityPanel />
      </div>
    </>
  );
}
