// /partner/help — Help & Guidelines.
//
// One place to find how to use the Command Center. Categorised cards
// + a search input so the partner reduces training burden on their
// CCEO over time.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerHelpCenter } from "@/components/partner/PartnerHelpCenter";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerHelpPage({
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
        title="Help & Guidelines"
        subtitle="How to schedule, deliver, prove, and get paid. Code of conduct and data rules too — everything in one place."
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12">
        <PartnerHelpCenter />
      </div>
    </>
  );
}
