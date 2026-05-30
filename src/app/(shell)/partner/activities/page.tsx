// /partner/activities — My Activities.
//
// Full list of every partner activity in one place. Reading order:
//   1. 4 KPI tiles (Total · Active · Overdue · This Month)
//   2. Status filter pills (All · Scheduled · In progress · etc.)
//   3. Scrollable table — priority, school, activity, status,
//      evidence %, due date, action
//
// Partner sub-page chrome via PartnerSubPageHeader.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { MyActivitiesTable } from "@/components/partner/MyActivitiesTable";

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
        filters={[
          { iconKey: "calendar", label: "All time" },
          { iconKey: "filter",   label: "All activity types" },
        ]}
        kpis={[
          { label: "Total activities",  value: 47, iconKey: "checks",     tone: "neutral", caption: "Across 2 districts" },
          { label: "Active",            value: 18, iconKey: "activity",   tone: "good",    caption: "In flight today"   },
          { label: "Overdue",           value: 2,  iconKey: "alert",      tone: "danger",  caption: "Need attention"    },
          { label: "Completed this mo", value: 11, iconKey: "cal-check",  tone: "good",    caption: "+3 vs Apr"         },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12">
        <MyActivitiesTable />
      </div>
    </>
  );
}
