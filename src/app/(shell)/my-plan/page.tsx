import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanView } from "@/components/mobile/views/PlanView";
import { PlanDesktopView } from "@/components/mobile/desktop-variants/PlanDesktopView";
import { PlansFamilyNav } from "@/components/planning/PlansFamilyNav";
import { getCurrentUser } from "@/lib/auth";

// Role-scoped: a Program Lead sees their team plan; a CCEO sees their
// Core Schools field plan. Other roles fall back to the PL plan.
export default async function Page() {
  const user = await getCurrentUser();

  return (
    <>
      <PlansFamilyNav current="my-plan" />
      <ResponsiveDashboard
        mobile={<PlanView role={user.role} />}
        desktop={<PlanDesktopView role={user.role} />}
      />
    </>
  );
}
