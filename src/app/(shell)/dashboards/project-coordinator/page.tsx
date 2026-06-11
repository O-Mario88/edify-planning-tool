import { redirect } from "next/navigation";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { CommandStack } from "@/components/actions/CommandStack";
import { SpHeader } from "@/components/special-projects/SpHeader";
import { SpKpiRow } from "@/components/special-projects/SpKpiRow";
import { SpActionBar } from "@/components/special-projects/SpActionBar";
import { ProjectPortfolioTable } from "@/components/special-projects/ProjectPortfolioTable";
import { PartnerDeliveryCard } from "@/components/special-projects/PartnerDeliveryCard";
import { ProjectImpactComparisonCard } from "@/components/special-projects/ProjectImpactComparisonCard";
import { ProjectWorkCard } from "@/components/special-projects/ProjectWorkCard";
import { computeSpecialProjectKpis, getVisibleProjects } from "@/lib/special-projects-mock";

// Project Coordinator console — the home for special projects & targeted
// interventions. Action-first (CommandStack), then the project portfolio,
// partner delivery, and the impact-comparison surface that answers
// "did the project move the SSA intervention it targets?".
export default async function ProjectCoordinatorDashboard() {
  const user = await getCurrentUser();
  if (!["ProjectCoordinator", "Admin"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }

  const currentUser = toCurrentUser(user);
  const visible = getVisibleProjects(currentUser);
  const kpis = computeSpecialProjectKpis(visible);

  return (
    <>
      <SpHeader />
      <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        {/* Layout rule: header → stats → work. The KPI row + action bar
            (stats) sit above the CommandStack (work), not below it. */}
        <SpKpiRow kpis={kpis} />
        <SpActionBar user={currentUser} />

        <CommandStack user={user} />

        <section className="grid grid-cols-12 gap-4 items-start">
          <div className="col-span-12 md:col-span-8">
            <ProjectPortfolioTable projects={visible} />
          </div>
          <div className="col-span-12 md:col-span-4 space-y-4">
            <ProjectWorkCard user={user} />
            <PartnerDeliveryCard />
          </div>
        </section>

        <ProjectImpactComparisonCard projects={visible} />
      </div>
    </>
  );
}
