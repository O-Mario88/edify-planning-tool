// /partner/activities — My Activities.
//
// Every partner activity in one place, live off the backend round-trip
// (Activity.assignedPartnerId → this org's session). Each row shows the
// activity type, school, status, and evidence status, with a real evidence
// action where one applies. The counts strip is derived from the backend
// response — no fabricated KPIs.
//
// Partner sub-page chrome via PartnerSubPageHeader.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerActivityListLive } from "@/components/partner/PartnerActivityListLive";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerActivitiesPage({
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
        title="My Activities"
        subtitle="Every partner activity you're responsible for — assigned, in flight, and closed."
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12">
        {/* Live, backend-driven: the activities actually assigned to this org,
            with the counts strip derived from the backend response. */}
        <PartnerActivityListLive filter="all" limit={100} />
      </div>
    </>
  );
}
