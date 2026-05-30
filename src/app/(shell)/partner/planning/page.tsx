// /partner/planning — Planning.
//
// Calendar/timeline view of partner delivery. Pinned-top strip
// surfaces every assigned activity that still needs scheduling so
// the partner can act on those first. Below: week buckets with
// capacity meters + facilitator pool.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerPlanningBoard } from "@/components/partner/PartnerPlanningBoard";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerPlanningPage({
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
        title="Planning"
        subtitle="Place assigned activities into delivery weeks. What you schedule here lands on your CCEO's monitoring dashboard automatically."
        filters={[
          { iconKey: "calendar", label: "May 2026" },
          { iconKey: "filter",   label: "All facilitators" },
        ]}
        kpis={[
          { label: "Unscheduled",       value: 3,     iconKey: "alert",     tone: "danger",  caption: "Need a delivery week"     },
          { label: "Scheduled · 4 wks", value: 11,    iconKey: "cal-range", tone: "good",    caption: "Across the month"         },
          { label: "Facilitators",      value: 5,     iconKey: "users",     tone: "neutral", caption: "Active on team"           },
          { label: "Capacity used",     value: "62%", iconKey: "calendar",  tone: "good",    caption: "Of weekly visit ceiling"  },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        <PartnerPlanningBoard />
      </div>
    </>
  );
}
