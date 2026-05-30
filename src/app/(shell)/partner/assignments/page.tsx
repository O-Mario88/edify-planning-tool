// /partner/assignments — My Plan.
//
// The partner's plan for the period: every activity that's been
// scheduled, delivered, awaiting confirmation, or paid. Unscheduled
// assignments live on /partner/schedule — the partner schedules
// them there, and they appear here once a delivery week is set.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { MyActivitiesTable } from "@/components/partner/MyActivitiesTable";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerMyPlanPage({
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
        title="My Plan"
        subtitle="Activities you've already scheduled — in flight, awaiting confirmation, or closed. Unscheduled assignments live on Schedule until you place them in a delivery week."
        filters={[
          { iconKey: "calendar", label: "All time" },
          { iconKey: "filter",   label: "All activity types" },
        ]}
        kpis={[
          { label: "On the plan",       value: 44, iconKey: "checks",    tone: "neutral", caption: "Scheduled + closed" },
          { label: "Active",            value: 18, iconKey: "activity",  tone: "good",    caption: "In flight today"    },
          { label: "Overdue",           value: 2,  iconKey: "alert",     tone: "danger",  caption: "Need attention"     },
          { label: "Completed this mo", value: 11, iconKey: "cal-check", tone: "good",    caption: "+3 vs Apr"          },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12">
        <MyActivitiesTable />
      </div>
    </>
  );
}
