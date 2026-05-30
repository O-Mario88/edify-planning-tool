import { PlanningToolPage } from "@/components/planning/PlanningToolPage";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanningMobileView } from "@/components/mobile/views/PlanningMobileView";

// The gap-based planning board now lives inside PlanningToolPage as a
// single tabbed switcher (Client Schools · Clusters · Core Schools) that
// drives the three neat, collapsible, detail-rich gap boards. The big
// gap-card layer and the separate Partner Assignments tab were retired:
// partner-planned schools surface under PlanningOwnershipSections /
// My Plan, not in the open-gap queue.
export default function Page() {
  return (
    <ResponsiveDashboard
      desktop={<PlanningToolPage />}
      mobile={<PlanningMobileView />}
    />
  );
}
