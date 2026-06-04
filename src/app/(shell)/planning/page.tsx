import { PlanningToolPage } from "@/components/planning/PlanningToolPage";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanningMobileView } from "@/components/mobile/views/PlanningMobileView";
import { coreBoardData } from "@/lib/core/core-board";
import { getCurrentUser } from "@/lib/auth";

// The gap-based planning board now lives inside PlanningToolPage as a
// single tabbed switcher (Client Schools · Clusters · Core Schools) that
// drives the three neat, collapsible, detail-rich gap boards. The Core
// Schools tab (desktop + mobile) consumes the unified CorePlan model.
export default async function Page() {
  const user = await getCurrentUser();
  const coreCards = coreBoardData(user.staffId, user.role);
  const coreViewer = {
    canAssign: ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"].includes(user.role),
    canExec: ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"].includes(user.role),
    canIa: ["ImpactAssessment", "Admin"].includes(user.role),
  };
  const canChampion = ["ImpactAssessment", "CountryProgramLead", "CountryDirector", "Admin"].includes(user.role);

  return (
    <ResponsiveDashboard
      desktop={<PlanningToolPage />}
      mobile={<PlanningMobileView coreCards={coreCards} coreViewer={coreViewer} canChampion={canChampion} />}
    />
  );
}
