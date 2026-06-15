// /partner/evidence — Evidence.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerEvidenceRequired } from "@/components/partner/PartnerEvidenceRequired";
import { PartnerEvidenceQualityPanel } from "@/components/partner/PartnerEvidenceQualityPanel";
import { EvidenceBulkDropzone, type EligibleActivity } from "@/components/partner/EvidenceBulkDropzone";
import { PartnerSubmitForVerification, type SubmitActivity } from "@/components/partner/PartnerSubmitForVerification";
import { partnerActivities } from "@/lib/actions/store";
import { fetchMyPartnerActivities } from "@/lib/api/surfaces";

const sfKind = (t: string): "visit" | "training" => (/train|meeting|sit|cluster/i.test(t) ? "training" : "visit");

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
  // Activities eligible for evidence upload = the partner's backend-assigned
  // work that isn't yet IA-verified / evidence-accepted. Live from
  // /partners/me/activities (the backend partner round-trip); the in-memory
  // store is the offline fallback. The ids are real backend Activity ids, so
  // the dropzone's POST /api/evidence/upload persists to that activity and the
  // IA sees the file in the verification queue.
  const TERMINAL = new Set(["ia_verified", "accountant_confirmed", "paid", "closed", "cancelled"]);
  const live = await fetchMyPartnerActivities(user);
  const eligible: EligibleActivity[] = live.live
    ? live.data.activities
        .filter((a) => a.evidenceStatus !== "accepted" && !TERMINAL.has(a.status))
        .map((a) => ({ id: a.id, title: `${a.activityType.replace(/_/g, " ")} · ${a.schoolName ?? "—"}`, schoolId: a.schoolName ?? "" }))
    : partnerActivities()
        .filter((a) => a.status === "Delivered")
        .map((a) => ({ id: a.id, title: a.title, schoolId: a.schoolId }));
  // Activities with evidence already uploaded — ready to submit for IA
  // verification (complete with a Salesforce ID -> awaiting_ia_verification).
  const readyToSubmit: SubmitActivity[] = live.live
    ? live.data.activities
        .filter((a) => a.status === "evidence_uploaded")
        .map((a) => ({ id: a.id, title: `${a.activityType.replace(/_/g, " ")} · ${a.schoolName ?? "—"}`, kind: sfKind(a.activityType) }))
    : [];
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
        <PartnerSubmitForVerification activities={readyToSubmit} />
        <PartnerEvidenceRequired />
        <PartnerEvidenceQualityPanel />
      </div>
    </>
  );
}
