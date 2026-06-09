import { redirect } from "next/navigation";
import { PlanningToolPage } from "@/components/planning/PlanningToolPage";
import { PlanningSetupLive } from "@/components/planning/PlanningSetupLive";
import { ClusterPlanningLive } from "@/components/planning/ClusterPlanningLive";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanningMobileView } from "@/components/mobile/views/PlanningMobileView";
import { coreBoardData, coreOwnershipRows } from "@/lib/core/core-board";
import { getCurrentUser } from "@/lib/auth";

// The gap-based planning board now lives inside PlanningToolPage as a
// single tabbed switcher (Client Schools · Clusters · Core Schools) that
// drives the three neat, collapsible, detail-rich gap boards. The Core
// Schools tab (desktop + mobile) consumes the unified CorePlan model.
// The gap-based board is a scope-wide planning view. A school-specific "Plan
// Action" must never land here generically — if a schoolId is passed, send it to
// that school's profile, which resolves the correct next action for it.
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const sid = Array.isArray(sp.schoolId) ? sp.schoolId[0] : sp.schoolId;
  if (sid) redirect(`/schools/${encodeURIComponent(sid)}?view=plan`);

  const user = await getCurrentUser();
  const coreCards = coreBoardData(user.staffId, user.role);
  const coreViewer = {
    canAssign: ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"].includes(user.role),
    canExec: ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"].includes(user.role),
    canIa: ["ImpactAssessment", "Admin"].includes(user.role),
  };
  const canChampion = ["ImpactAssessment", "CountryProgramLead", "CountryDirector", "Admin"].includes(user.role);
  const coreOwnership = coreOwnershipRows(user.staffId, user.role);

  return (
    <ResponsiveDashboard
      desktop={
        <div className="px-3 sm:px-4 md:px-5 pt-3 md:pt-4 space-y-3">
          {/* Planning = what still needs to be scheduled (gaps + recommendations).
              My Plan (what's already scheduled) is its own page at /my-plan. */}
          <PlanningSetupLive />
          <ClusterPlanningLive />
          <PlanningToolPage />
        </div>
      }
      mobile={
        <div className="px-3 pt-3 space-y-3">
          <PlanningSetupLive />
          <PlanningMobileView coreCards={coreCards} coreViewer={coreViewer} canChampion={canChampion} coreOwnership={coreOwnership} />
        </div>
      }
    />
  );
}
