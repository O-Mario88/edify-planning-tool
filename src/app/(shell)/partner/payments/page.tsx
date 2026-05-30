// /partner/payments — Payment Status.
//
// Shows only the partner's own payment workflow — no internal Edify
// finance. Reuses the 7-state PartnerPaymentStatusCard from the
// Command Center and adds a per-activity table so the partner can
// see what's blocking each payment.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerPaymentStatusCard } from "@/components/partner/PartnerPaymentStatusCard";
import { PartnerPaymentLedger } from "@/components/partner/PartnerPaymentLedger";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerPaymentsPage({
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
        title="Payments"
        subtitle="Every activity's payment state in one place — no need to chase anyone. We update the moment your CCEO confirms, your PL approves, or the accountant clears."
        kpis={[
          { label: "Paid this month",       value: "UGX 5.6M",  iconKey: "shield", tone: "good",   caption: "16 activities cleared" },
          { label: "In flight",             value: "UGX 3.5M",  iconKey: "rotate", tone: "warn",   caption: "10 awaiting approval"   },
          { label: "Not eligible yet",      value: 14,          iconKey: "clock",  tone: "warn",   caption: "Evidence incomplete"     },
          { label: "On hold / returned",    value: 3,           iconKey: "alert",  tone: "danger", caption: "Need partner action"     },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        <PartnerPaymentStatusCard />
        <PartnerPaymentLedger />
      </div>
    </>
  );
}
