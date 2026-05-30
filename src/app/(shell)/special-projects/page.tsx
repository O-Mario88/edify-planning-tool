import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SpecialProjectsMobileView } from "@/components/mobile/views/SpecialProjectsMobileView";
import { SpHeader } from "@/components/special-projects/SpHeader";
import { SpKpiRow } from "@/components/special-projects/SpKpiRow";
import { SpActionBar } from "@/components/special-projects/SpActionBar";
import { ProjectPortfolioTable } from "@/components/special-projects/ProjectPortfolioTable";
import { PriorityProjectsPanel } from "@/components/special-projects/PriorityProjectsPanel";
import { ProjectImpactOverviewCard } from "@/components/special-projects/ProjectImpactOverviewCard";
import { SchoolsInProjectsCard } from "@/components/special-projects/SchoolsInProjectsCard";
import { PartnerDeliveryCard } from "@/components/special-projects/PartnerDeliveryCard";
import { TeacherImpactTrackerCard } from "@/components/special-projects/TeacherImpactTrackerCard";
import { UpcomingMilestonesCalendar } from "@/components/special-projects/UpcomingMilestonesCalendar";
import {
  computeSpecialProjectKpis,
  getVisibleProjects,
} from "@/lib/special-projects-mock";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";

// The Special Projects Module sits OUTSIDE the SSA 8 interventions but
// integrates with staff capacity, fund requests, Salesforce logging,
// verification, and the School 360 profile — see special-projects-mock.ts
// for the role-aware visibility filter and the strict separation between
// teacher-impact and school-impact projects.
export default async function SpecialProjectsDashboard() {
  const currentUser = toCurrentUser(await getCurrentUser());
  const visible = getVisibleProjects(currentUser);
  const kpis = computeSpecialProjectKpis(visible);

  return (
    <ResponsiveDashboard mobile={<SpecialProjectsMobileView />} desktop={
    <>
      <SpHeader />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          {/* Hero banner retired per global hero removal pass. */}

          {/* KPI row — 8 cards */}
          <SpKpiRow kpis={kpis} />

          {/* Action bar — primary CTA + 5 outline actions */}
          <SpActionBar user={currentUser} />

          {/* Project Portfolio + Priority Projects */}
          <section className="grid grid-cols-12 gap-4 items-start">
            <div className="col-span-12 md:col-span-8">
              <ProjectPortfolioTable projects={visible} />
            </div>
            <div className="col-span-12 md:col-span-4" id="priority">
              <PriorityProjectsPanel />
            </div>
          </section>

          {/* Project Impact Overview (full width) */}
          <ProjectImpactOverviewCard />

          {/* Schools in Projects + Partner Delivery + Teacher Impact Tracker */}
          <section className="grid grid-cols-12 gap-4 items-start">
            <div className="col-span-12 md:col-span-4">
              <SchoolsInProjectsCard />
            </div>
            <div className="col-span-12 md:col-span-4">
              <PartnerDeliveryCard />
            </div>
            <div className="col-span-12 md:col-span-4">
              <TeacherImpactTrackerCard projects={visible} />
            </div>
          </section>

          {/* Upcoming Milestones / Project Calendar (full width) */}
          <UpcomingMilestonesCalendar />
        </div>
      </>
    } />
  );
}
