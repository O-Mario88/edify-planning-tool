import { redirect } from "next/navigation";
import { PlanningToolPage } from "@/components/planning/PlanningToolPage";
import { PlanningSetupLive } from "@/components/planning/PlanningSetupLive";
import { ClusterPlanningLive } from "@/components/planning/ClusterPlanningLive";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanningMobileView } from "@/components/mobile/views/PlanningMobileView";
import { coreBoardData, coreOwnershipRows } from "@/lib/core/core-board";
import { getCurrentUser } from "@/lib/auth";
import { SmartGroupingCard } from "@/components/planning/SmartGroupingCard";

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
        /* Planning = what still needs to be scheduled (gaps + recommendations).
           My Plan (what's already scheduled) is its own page at /my-plan.
           The live setup cards render through PlanningToolPage's topSlot so
           the canonical header stays the FIRST element on the page. */
        <PlanningToolPage
          searchParams={sp}
          topSlot={
            <>
              <SmartGroupingCard assignedCceo={user.role === "CCEO" ? user.name : undefined} />
              <PlanningSetupLive role={user.role} />
              <ClusterPlanningLive />
            </>
          }
        />
      }
      mobile={
        <div className="px-3 pt-3 space-y-3">
          <SmartGroupingCard assignedCceo={user.role === "CCEO" ? user.name : undefined} />
          <PlanningSetupLive role={user.role} />
          <PlanningMobileView coreCards={coreCards} coreViewer={coreViewer} canChampion={canChampion} coreOwnership={coreOwnership} />
        </div>
      }
    />
  );
}
