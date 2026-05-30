// /partner/profile — Partner Profile.
//
// Read-only surface for contract + scope + people. Anything the
// partner can't change directly gets a "Request change" CTA that
// routes through Edify staff.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerProfileSheet } from "@/components/partner/PartnerProfileSheet";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerProfilePage({
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
        title="Partner Profile"
        subtitle="Your contract, scope, people, and reporting requirements with Edify. Anything that needs an update routes through your CCEO."
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        <PartnerProfileSheet />
      </div>
    </>
  );
}
