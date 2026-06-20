import { redirect } from "next/navigation";
import { PlanningToolPage } from "@/components/planning/PlanningToolPage";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanningMobileView } from "@/components/mobile/views/PlanningMobileView";
import { coreBoardData, coreOwnershipRows } from "@/lib/core/core-board";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
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
  // The mobile Core Plan board + ownership sections are fed from dev-only mock
  // fixtures (no backend endpoint for the mobile core board yet). Gate them so
  // production renders the controlled empty state, never fabricated core schools.
  // (Desktop's Core Schools tab is backend-driven through PlanningToolPage.)
  const mockOk = isMockAllowed();
  const coreCards = mockOk ? coreBoardData(user.staffId, user.role) : [];
  const coreViewer = {
    canAssign: ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"].includes(user.role),
    canExec: ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"].includes(user.role),
    canIa: ["ImpactAssessment", "Admin"].includes(user.role),
  };
  const canChampion = ["ImpactAssessment", "CountryProgramLead", "CountryDirector", "Admin"].includes(user.role);
  const coreOwnership = mockOk ? coreOwnershipRows(user.staffId, user.role) : undefined;

  return (
    <ResponsiveDashboard
      desktop={
        /* Planning = what still needs to be scheduled (gaps + recommendations).
           My Plan (what's already scheduled) is its own page at /my-plan.
           The live setup cards render through PlanningToolPage's topSlot so
           the canonical header stays the FIRST element on the page. */
        <PlanningToolPage
          searchParams={sp}
          /* SmartGroupingCard derives its suggestions from the intake mock, so it
             only renders when mock data is allowed (dev opt-in) — never in prod. */
          topSlot={
            mockOk ? <SmartGroupingCard assignedCceo={user.role === "CCEO" ? user.name : undefined} /> : undefined
          }
        />
      }
      mobile={
        <div className="px-3 pt-3 space-y-3">
          {mockOk && <SmartGroupingCard assignedCceo={user.role === "CCEO" ? user.name : undefined} />}
          <PlanningMobileView coreCards={coreCards} coreViewer={coreViewer} canChampion={canChampion} coreOwnership={coreOwnership} />
        </div>
      }
    />
  );
}
