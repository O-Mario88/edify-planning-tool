import { BarChart3 } from "lucide-react";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { PageHeader } from "@/components/ui/PageHeader";
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
      <PageHeader
        title="Core Analytics"
        subtitle="Candidate → Verified → Onboarded → 4+4 Complete → Follow-Up SSA → Improved → Champion. Scoped to your portfolio."
        Icon={BarChart3}
      />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 pt-3">
        <CoreAnalyticsView a={a} />
      </div>
      <RoleBottomNav />
    </>
  );
  return <ResponsiveDashboard mobile={body} desktop={body} />;
}
