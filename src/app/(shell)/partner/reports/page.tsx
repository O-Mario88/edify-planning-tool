// /partner/reports — Reports.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerReportsBoard } from "@/components/partner/PartnerReportsBoard";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerReportsPage({
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
        title="Reports"
        subtitle="Submit weekly and monthly partner reports, and download past submissions shared with Edify leadership."
        filters={[
          { iconKey: "calendar", label: "Last 6 months" },
          { iconKey: "filter",   label: "All report types" },
        ]}
        kpis={[
          { label: "Submitted",      value: 14,    iconKey: "send",      tone: "good",    caption: "On time"            },
          { label: "Pending",        value: 2,     iconKey: "cal-range", tone: "warn",    caption: "Due this week"       },
          { label: "Reports in lib", value: 47,    iconKey: "file",      tone: "neutral", caption: "Past 6 months"       },
          { label: "On-time rate",   value: "96%", iconKey: "sparkles",  tone: "good",    caption: "12-month rolling"    },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12">
        <PartnerReportsBoard />
      </div>
    </>
  );
}
