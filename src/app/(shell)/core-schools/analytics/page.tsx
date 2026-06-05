import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreAnalyticsView } from "@/components/core/CoreAnalyticsView";
import { coreAnalytics } from "@/lib/core/core-analytics";
import { getCurrentUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Core Analytics — the lifecycle aggregated into funnel, package progress,
// before/after, delivery split, and intervention heatmap. Role-scoped; every
// number drills back to real CorePlan / CoreActivitySlot / CoreImpact records.
export default async function CoreAnalyticsPage() {
  const user = await getCurrentUser();
  const a = coreAnalytics(user.staffId, user.role);
  const body = (
    <>
      <CorePageHeader
        icon="analytics"
        title="Core Analytics"
        subtitle="Candidate → Verified → Onboarded → 4+4 Complete → Follow-Up SSA → Improved → Champion. Scoped to your portfolio."
      />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 pt-3">
        <CoreAnalyticsView a={a} />
      </div>
      <RoleBottomNav />
    </>
  );
  return body;
}
