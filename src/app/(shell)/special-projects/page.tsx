import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SpecialProjectsMobileView } from "@/components/mobile/views/SpecialProjectsMobileView";
import { SpHeader } from "@/components/special-projects/SpHeader";
import { SpActionBar } from "@/components/special-projects/SpActionBar";
import { SpecialProjectsLiveOverview } from "@/components/special-projects/SpecialProjectsLiveOverview";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";

// The Special Projects Module sits OUTSIDE the SSA 8 interventions. This page is
// driven ENTIRELY by the live backend Project graph — the backend emits only
// {name, code, category, intervention, schoolCount, partnerCount, activityCount,
// latestImpact}, so the overview shows ONLY metrics derivable from that: the KPI
// strip, the live project board, per-project intervention impact (before→after
// SSA), and partner delivery (completed/total). There is no project status /
// health / budget / dates / teacher-target in the graph, so those cards were
// removed rather than faked. Each project deep-links to /projects/[id] — the full
// live monitor (ProjectMonitorLive) with Schedule / Assign / partner add-remove.
export default async function SpecialProjectsDashboard() {
  const currentUser = toCurrentUser(await getCurrentUser());

  return (
    <ResponsiveDashboard mobile={<SpecialProjectsMobileView />} desktop={
    <>
      <SpHeader />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          {/* Action bar — single working CTA (New Project) */}
          <SpActionBar user={currentUser} />

          {/* Everything below is live from the backend Project graph. */}
          <SpecialProjectsLiveOverview />
        </div>
      </>
    } />
  );
}
