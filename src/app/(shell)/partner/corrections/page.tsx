// /partner/corrections — Corrections.
//
// Items returned by CCEO, PL, accountant, or M&E. Surfaces the
// standardised reason + plain-English "what to fix" guidance so the
// partner can act without a back-and-forth.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerReturnedCorrections } from "@/components/partner/PartnerReturnedCorrections";

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
        subtitle="Items returned by your CCEO, PL, or M&amp;E. Each row tells you exactly what to fix — no back-and-forth needed."
        kpis={[
          { label: "To correct",          value: 3,         iconKey: "rotate", tone: "warn",    caption: "Open returns" },
          { label: "Avg fix time",        value: "1.4 days",iconKey: "clock",  tone: "warn",    caption: "Median this month" },
          { label: "Resolved this month", value: 12,        iconKey: "shield", tone: "good",    caption: "Cleared and re-submitted" },
          { label: "Blocking payment",    value: 1,         iconKey: "alert",  tone: "danger",  caption: "Of the 3 open returns" },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12">
        <PartnerReturnedCorrections />
      </div>
    </>
  );
}
